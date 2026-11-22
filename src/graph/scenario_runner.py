"""Scripted graph scenarios (Phase 6 functional tests). Tasks live in a real Phase 5 store; edges go through the real
GraphEditor (same validator/history as chat-derived edges); status changes go through Reconciler.manual_edit.
Developer-authored fixtures, NOT an independent benchmark."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from src.graph.graph_builder import WorkflowGraph, make_edge_id
from src.graph.graph_editor import GraphEditor
from src.graph.serialize import to_frontend
from src.graph.workflow_state import compute_states, diff_states, impact_of
from src.reconciliation.models import ReconciliationError, StaleVersion, Task
from src.reconciliation.reconciler import Reconciler
from src.reconciliation.store import TaskStore

WS = "w"


def _clock():
    n = {"i": 0}

    def c():
        n["i"] += 1
        return f"2026-11-11T00:{n['i'] // 60:02d}:{n['i'] % 60:02d}+00:00"
    return c


def make_due(v: Optional[str]) -> Optional[dict]:
    if v is None:
        return None
    if v.startswith("~"):   # unresolved expression
        return {"raw": v[1:], "status": "UNRESOLVED_EVENT_CONDITION", "value": None}
    return {"raw": v, "status": "RESOLVED", "granularity": "DATE", "value": v, "start": v, "end": v}


def build_store(tasks: list[Mapping[str, Any]]) -> TaskStore:
    store = TaskStore(":memory:", clock=_clock())
    with store.transaction():
        for t in tasks:
            tid = store.next_task_id(WS)
            task = Task(task_id=tid, workspace_id=WS, thread_id=t.get("thread", "th1"), title=t.get("title", f"task {tid}"),
                        owner_id=t.get("owner"), due=make_due(t.get("due")), status=t.get("status", "open"), source_message_id="m0",
                        created_by="riya", created_at=store.now())
            store.insert_task(task)
            store.append_history(WS, tid, operation="CREATE_TASK", field="__create__", before=None,
                                after={"title": task.title, "owner_id": task.owner_id, "due": task.due, "scheduled": None, "status": task.status,
                                       "pending_changes": {}}, actor="riya", source_kind="scripted")
    return store


def _edge_id(store, pre, dep):
    return make_edge_id(WS, dep, pre)


def run_graph_scenario(sc: Mapping[str, Any], *, validator=None) -> dict[str, Any]:
    store = build_store(sc["tasks"])
    editor = GraphEditor(store, validator)
    rec = Reconciler(store)
    failures: list[str] = []
    name = sc["name"]

    def fail(i, msg):
        failures.append(f"[{name}] step {i}: {msg}")

    for i, step in enumerate(sc["steps"], 1):
        actor = step.get("actor", "riya")
        exp = step.get("expect", {})
        try:
            if "add" in step:
                pre, dep = step["add"]
                r = editor.add_dependency(WS, pre, dep, actor, evidence=step.get("evidence", ""), idempotency_key=step.get("key"))
                for k in ("status", "code", "applied"):
                    if k in exp and r.get(k) != exp[k]:
                        fail(i, f"add {pre}->{dep}: {k}={r.get(k)!r}, expected {exp[k]!r}")
                if "warnings" in exp and sorted(r.get("warnings", [])) != sorted(exp["warnings"]):
                    fail(i, f"warnings {r.get('warnings')} != {exp['warnings']}")
                if "cycle_path" in exp and r.get("cycle_path") != exp["cycle_path"]:
                    fail(i, f"cycle_path {r.get('cycle_path')} != {exp['cycle_path']}")
                if "replayed" in exp and bool(r.get("replayed")) != exp["replayed"]:
                    fail(i, f"replayed={r.get('replayed')}, expected {exp['replayed']}")
            elif "remove" in step:
                pre, dep = step["remove"]
                r = editor.remove_dependency(WS, _edge_id(store, pre, dep), actor, step.get("reason", ""))
                if "applied" in exp and r.get("applied") != exp["applied"]:
                    fail(i, f"remove applied={r.get('applied')}")
            elif "reconsider" in step:
                pre, dep = step["reconsider"]
                r = editor.reconsider(WS, _edge_id(store, pre, dep), actor)
                for k in ("status", "code"):
                    if k in exp and r.get(k) != exp[k]:
                        fail(i, f"reconsider {pre}->{dep}: {k}={r.get(k)!r}, expected {exp[k]!r}")
            elif "status" in step:
                tid, new = step["status"]
                before = compute_states(WorkflowGraph.from_store(store, WS))
                t = store.get_task(WS, tid)
                rec.manual_edit(WS, tid, actor, t.version, {"status": new})
                after = compute_states(WorkflowGraph.from_store(store, WS))
                _check_diff(diff_states(before, after).to_dict(), step.get("expect_diff"), fail, i)
            elif "impact" in step:
                tid, new = step["impact"]
                before_versions = {t.task_id: t.version for t in store.list_tasks(WS)}
                _check_diff(impact_of(WorkflowGraph.from_store(store, WS), tid, new).to_dict(), step.get("expect_diff"), fail, i)
                if {t.task_id: t.version for t in store.list_tasks(WS)} != before_versions:
                    fail(i, "what-if changed the store")
            elif "check" in step:
                _check_graph(WorkflowGraph.from_store(store, WS), step["check"], fail, i)
            else:
                fail(i, f"unknown step {step}")
        except (ReconciliationError, StaleVersion) as e:
            fail(i, f"unexpected {type(e).__name__}: {e}")
    g = WorkflowGraph.from_store(store, WS)
    if not g.acyclic:
        fail("final", f"accepted graph has a cycle: {g.cycle}")
    return {"name": name, "passed": not failures, "failures": failures, "store": store, "graph": to_frontend(g)}


def _check_diff(got: dict, want: Optional[Mapping[str, Any]], fail, i) -> None:
    for k, v in (want or {}).items():
        if got.get(k) != v:
            fail(i, f"diff.{k} = {got.get(k)!r}, expected {v!r}")


def _check_graph(g: WorkflowGraph, want: Mapping[str, Any], fail, i) -> None:
    states = compute_states(g)
    for tid, d in want.get("states", {}).items():
        if states[tid].derived != d:
            fail(i, f"{tid} derived={states[tid].derived!r}, expected {d!r}")
    for tid, b in want.get("blocked_by", {}).items():
        if states[tid].blocked_by != b:
            fail(i, f"{tid} blocked_by={states[tid].blocked_by}, expected {b}")
    for tid, b in want.get("cancelled_prereqs", {}).items():
        if states[tid].cancelled_prereqs != b:
            fail(i, f"{tid} cancelled_prereqs={states[tid].cancelled_prereqs}, expected {b}")
    for tid, b in want.get("root_blockers", {}).items():
        if states[tid].root_blockers != b:
            fail(i, f"{tid} root_blockers={states[tid].root_blockers}, expected {b}")
    if "acyclic" in want and g.acyclic != want["acyclic"]:
        fail(i, f"acyclic={g.acyclic}")
    if "kinds" in want:
        got = {"accepted": len(g.accepted()), "held": len(g.held()), "proposed": len(g.proposed())}
        for k, v in want["kinds"].items():
            if got[k] != v:
                fail(i, f"{k} edges={got[k]}, expected {v}")
    if "order" in want and g.topological_order() != want["order"]:
        fail(i, f"order={g.topological_order()}, expected {want['order']}")
    if "layers" in want and g.layers() != want["layers"]:
        fail(i, f"layers={g.layers()}, expected {want['layers']}")
    for key, w in want.get("edge_warnings", {}).items():
        pre, dep = key.split(">")
        e = g.get_edge(pre, dep)
        if e is None or sorted(e.warnings) != sorted(w):
            fail(i, f"edge {key} warnings={None if e is None else e.warnings}, expected {w}")
    for key, rsn in want.get("edge_reason_prefix", {}).items():
        pre, dep = key.split(">")
        e = g.get_edge(pre, dep)
        if e is None or not e.reason.startswith(rsn):
            fail(i, f"edge {key} reason={None if e is None else e.reason!r}, expected prefix {rsn!r}")
    if "longest_chain" in want and g.longest_chain() != want["longest_chain"]:
        fail(i, f"longest_chain={g.longest_chain()}")
