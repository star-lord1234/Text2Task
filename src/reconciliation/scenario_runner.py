"""Scripted multi-turn scenario runner (Phase 5 functional tests).

A scenario is a compact JSON script: participants plus messages. Each message lists entity spans and
links (the extractor output is *scripted*, so scenarios test reconciliation logic, not ML accuracy) and
reviewer actions. The runner builds Phase 4 candidates from the scripted spans, runs the reconciler,
applies the review actions, and checks expectations. Every scenario is also checked for history
reconstruction (history alone must rebuild each task's current state) and stable task ids.

These are functional fixtures authored by the developer. They are NOT an independent benchmark.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from src.pipeline.contracts import MessageEnvelope, Participant
from src.pipeline.identity_resolution import ParticipantRegistry
from src.pipeline.task_fields import build_task_candidates
from src.reconciliation.models import ReconciliationError, StaleVersion
from src.reconciliation.reconciler import Reconciler
from src.reconciliation.store import TaskStore

RELATION_SCORE = 0.95


def _locate(text: str, spec: str) -> tuple[int, int, str]:
    """'phrase' or 'phrase#2' (second occurrence) -> (start, end, phrase)."""
    phrase, _, nth = spec.partition("#")
    start = -1
    for _ in range(int(nth) if nth else 1):
        start = text.index(phrase, start + 1)
    return start, start + len(phrase), phrase


def build_entities(text: str, spans: Mapping[str, list[str]]) -> tuple[list[dict], dict[str, str]]:
    found = []
    for typ, specs in spans.items():
        for spec in specs:
            s, e, phrase = _locate(text, spec)
            found.append((s, e, typ, phrase, spec))
    found.sort()
    entities, ids = [], {}
    for i, (s, e, typ, phrase, spec) in enumerate(found, 1):
        eid = f"e{i}"
        entities.append({"id": eid, "type": typ, "start": s, "end": e, "text": phrase})
        ids[spec] = eid
        ids.setdefault(phrase, eid)
    return entities, ids


def _options(m: Mapping[str, Any], *, text: str, ids: Mapping[str, str]) -> Optional[dict[str, Any]]:
    """Phase 7.5 reconciler options from a scenario message. Strings in place of entity ids/offsets are resolved against the message text:
    {"imperative": ["phrase"]} -> imperative_ids; {"hints": [{"dependent": "phrase", "prerequisite": "clause text", ...}]} -> clause_hints."""
    o = m.get("options")
    if not o:
        return None
    out: dict[str, Any] = {"context_lifecycle": bool(o.get("context_lifecycle"))}
    if o.get("imperative"):
        out["imperative_ids"] = [ids[x] for x in o["imperative"]]
    hints = []
    for h in o.get("hints", []):
        a = text.index(h["prerequisite"])
        d = text.index(h["dependent_text"]) if h.get("dependent_text") else 0
        hints.append({"kind": h["kind"], "pattern": "scenario", "cue": h.get("cue"), "rule": "scenario",
                      "dependent_entity_id": ids.get(h.get("dependent")) if h.get("dependent") else None,
                      "dependent_text": h.get("dependent_text"), "dependent_range": [d, d + len(h.get("dependent_text") or "")],
                      "prerequisite_text": h["prerequisite"], "prerequisite_range": [a, a + len(h["prerequisite"])]})
    out["clause_hints"] = hints
    return out


def _state(t) -> dict[str, Any]:
    def d(v):
        return None if not v else (v.get("value") or v.get("start"))
    pend = {k: (d(v.get("value")) if isinstance(v, dict) else None) for k, v in (t.pending_changes or {}).items()}
    return {"title": t.title, "owner_id": t.owner_id, "status": t.status, "version": t.version, "due": d(t.due),
            "scheduled": d(t.scheduled), "pending_due": pend.get("due"), "pending_scheduled": pend.get("scheduled")}


def run_scenario(scenario: Mapping[str, Any], *, reconciler: Optional[Reconciler] = None, ws: str = "w") -> dict[str, Any]:
    store = TaskStore(":memory:", clock=_clock())
    rec = reconciler or Reconciler(store)
    store = rec.store
    registry = ParticipantRegistry([Participant(**p) for p in scenario["participants"]])
    failures: list[str] = []
    trace: list[dict[str, Any]] = []
    op_counts: dict[str, int] = {}
    by_msg: dict[str, Any] = {}

    def fail(msg_id, msg):
        failures.append(f"[{scenario['name']}] {msg_id}: {msg}")

    for m in scenario["messages"]:
        mid = m["id"]
        env = MessageEnvelope(mid, m["text"], m.get("sender"), m.get("recipients", []), m.get("ts"), m.get("tz"),
                              m.get("thread", "th1"), m.get("reply_to"))
        entities, ids = build_entities(m["text"], m.get("spans", {}))
        rels = [{"source_id": ids[a], "target_id": ids[b], "label": lab, "score": RELATION_SCORE, "provenance": "scripted",
                 "model_version": "scenario"} for a, b, lab in m.get("links", [])]
        cands = build_task_candidates(env, entities, rels, registry, primary_source="scripted", config=rec.phase4_config)
        before_counts = store.counts(ws)
        try:
            res = rec.process_message(env, entities, cands, registry, workspace_id=ws, source_kind="scripted", options=_options(m, text=m["text"], ids=ids))
        except ReconciliationError as e:
            exp = m.get("expect_error")
            if exp != e.code:
                fail(mid, f"unexpected error {e.code}")
            continue
        if m.get("expect_error"):
            fail(mid, f"expected error {m['expect_error']} but processing succeeded")
        allp = res.proposals + res.no_actions
        by_msg[mid] = res
        ops = [p.operation for p in allp]
        for o in ops:
            op_counts[o] = op_counts.get(o, 0) + 1
        exp = m.get("expect", {})
        if "ops" in exp and ops != exp["ops"]:
            fail(mid, f"operations {ops} != expected {exp['ops']}")
        codes = {f["code"] for p in allp for f in p.flags}
        for c in exp.get("flags", []):
            if c not in codes:
                fail(mid, f"missing flag {c} (have {sorted(codes)})")
        for c in exp.get("no_flags", []):
            if c in codes:
                fail(mid, f"unexpected flag {c}")
        if "pending" in exp and len(res.proposals) != exp["pending"]:
            fail(mid, f"{len(res.proposals)} reviewable proposals != expected {exp['pending']}")
        if m.get("replay"):
            again = rec.process_message(env, entities, cands, registry, workspace_id=ws, source_kind="scripted")
            if not again.replayed or [p.proposal_id for p in again.proposals + again.no_actions] != [p.proposal_id for p in allp]:
                fail(mid, "replay did not return the same proposals")
            if store.counts(ws)["proposals"] != before_counts["proposals"] + len(allp):
                fail(mid, "replay created additional proposal rows")

        applied: dict[str, Any] = {}
        for act in m.get("review", []):
            _review(rec, ws, res, act, fail, mid, by_msg)

        for tid, want in exp.get("tasks", {}).items():
            t = store.get_task(ws, tid)
            if t is None:
                fail(mid, f"task {tid} does not exist")
                continue
            st = _state(t)
            for k, v in want.items():
                if k == "history_len":
                    if len(store.history_for(ws, tid)) != v:
                        fail(mid, f"{tid} history_len {len(store.history_for(ws, tid))} != {v}")
                elif st.get(k) != v:
                    fail(mid, f"{tid}.{k} = {st.get(k)!r}, expected {v!r}")
        if "task_count" in exp and len(store.list_tasks(ws)) != exp["task_count"]:
            fail(mid, f"task_count {len(store.list_tasks(ws))} != {exp['task_count']}")
        if "dependencies" in exp:
            got = sorted((d.dependent_task_id, d.prerequisite_task_id, d.status) for d in store.list_dependencies(ws))
            want = sorted(tuple(x) for x in exp["dependencies"])
            if got != want:
                fail(mid, f"dependencies {got} != {want}")
        trace.append({"message": mid, "operations": ops, "flags": sorted(codes)})

    # invariants: history alone reconstructs every task; ids are contiguous; history is chain-consistent
    for t in store.list_tasks(ws):
        state = TaskStore.reconstruct(store.history_for(ws, t.task_id))
        actual = {"title": t.title, "owner_id": t.owner_id, "status": t.status, "due": t.due, "scheduled": t.scheduled,
                  "pending_changes": t.pending_changes}
        for k, v in actual.items():
            if state.get(k) != v:
                fail("invariant", f"{t.task_id}: history reconstructs {k}={state.get(k)!r} but task has {v!r}")
    ids_ = [t.task_id for t in store.list_tasks(ws)]
    if ids_ != [f"T-{i}" for i in range(1, len(ids_) + 1)]:
        fail("invariant", f"task ids not contiguous: {ids_}")
    return {"name": scenario["name"], "passed": not failures, "failures": failures, "trace": trace, "operation_counts": op_counts,
            "tasks": {t.task_id: _state(t) for t in store.list_tasks(ws)}, "store": store}


def _review(rec, ws, res, act, fail, mid, by_msg) -> None:
    pending = list(res.proposals)

    def pick(sel):
        if sel == "all":
            return [p for p in pending if p.operation != "NO_ACTION"]
        if isinstance(sel, int):
            return [pending[sel]]
        if isinstance(sel, dict) and "op" in sel:
            pool = list(by_msg[sel["message"]].proposals) if sel.get("message") else pending
            return [next(p for p in pool if p.operation == sel["op"])]
        raise ValueError(sel)

    if "reject_pending" in act:
        r = act["reject_pending"]
        t = rec.store.get_task(ws, r["task"])
        rec.reject_pending_change(ws, r["task"], r["field"], r.get("actor", "reviewer"), expected_version=t.version, reason="declined")
        return
    if "manual_edit" in act:
        r = act["manual_edit"]
        t = rec.store.get_task(ws, r["task"])
        ev = r.get("expected_version", t.version)
        try:
            rec.manual_edit(ws, r["task"], r.get("actor", "reviewer"), ev, r["changes"], idempotency_key=r.get("key"))
            if act.get("expect_error"):
                fail(mid, f"manual_edit expected error {act['expect_error']}")
        except StaleVersion:
            if act.get("expect_error") != "STALE_VERSION":
                fail(mid, "manual_edit raised STALE_VERSION unexpectedly")
        except ReconciliationError as e:
            if act.get("expect_error") != e.code:
                fail(mid, f"manual_edit error {e.code} unexpected")
        return
    try:
        targets = pick(act.get("accept", act.get("dismiss")))
    except StopIteration:
        fail(mid, f"no pending proposal matches {act.get('accept', act.get('dismiss'))}")
        return
    for p in targets:
        if "dismiss" in act:
            rec.dismiss(ws, p.proposal_id, act.get("actor", "reviewer"), act.get("reason", ""))
            continue
        try:
            rec.accept(ws, p.proposal_id, act.get("actor", "reviewer"), edits=act.get("edits"),
                       expected_version=act.get("expected_version"), idempotency_key=act.get("key"))
            if act.get("expect_error"):
                fail(mid, f"accept of {p.operation} expected error {act['expect_error']} but succeeded")
        except StaleVersion:
            if act.get("expect_error") != "STALE_VERSION":
                fail(mid, f"accept of {p.operation} raised STALE_VERSION unexpectedly")
        except ReconciliationError as e:
            if act.get("expect_error") != e.code:
                fail(mid, f"accept of {p.operation} raised {e.code} unexpectedly")
        if act.get("then_accept_again"):
            r = rec.accept(ws, p.proposal_id, act.get("actor", "reviewer"), idempotency_key=act.get("key"))
            if not r.get("replayed"):
                fail(mid, "second accept with the same key was not an idempotent replay")


def _clock():
    n = {"i": 0}

    def clock():
        n["i"] += 1
        return f"2026-11-11T00:{n['i'] // 60:02d}:{n['i'] % 60:02d}+00:00"
    return clock
