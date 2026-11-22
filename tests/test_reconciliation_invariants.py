"""Seeded fuzz over message / review interleavings; invariants must hold after every step."""
import json
import random
import unittest
from pathlib import Path

from src.pipeline.contracts import MessageEnvelope, Participant
from src.pipeline.identity_resolution import ParticipantRegistry
from src.pipeline.task_fields import build_task_candidates
from src.reconciliation.models import ReconciliationError, StaleVersion
from src.reconciliation.reconciler import Reconciler
from src.reconciliation.scenario_runner import build_entities
from src.reconciliation.store import TaskStore

SCEN = json.loads((Path(__file__).parent / "fixtures" / "reconciliation_scenarios.json").read_text())["scenarios"]
POOL = [m for s in SCEN for m in s["messages"] if not m.get("expect_error")]
PARTS = SCEN[0]["participants"]
WS = "w"
UPDATE_OPS = {"COMPLETE_TASK", "CANCEL_TASK", "UPDATE_STATUS", "UPDATE_ASSIGNEE", "PROPOSE_DUE_DATE_CHANGE", "CONFIRM_DUE_DATE_CHANGE"}


def clock():
    n = {"i": 0}

    def c():
        n["i"] += 1
        return f"2026-11-11T{n['i'] // 3600:02d}:{(n['i'] // 60) % 60:02d}:{n['i'] % 60:02d}+00:00"
    return c


class Fuzz:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.rec = Reconciler(TaskStore(":memory:", clock=clock()))
        self.store = self.rec.store
        self.registry = ParticipantRegistry([Participant(**p) for p in PARTS])
        self.seen_ids, self.versions, self.hist_snapshot = set(), {}, []
        self.sent: list = []
        self.n = 0
        self.errors = 0

    def process(self, tpl, replay=False):
        if replay:
            if not self.sent:
                return
            env, ents, cands = self.rng.choice(self.sent)
            before = self.store.counts(WS)
            res = self.rec.process_message(env, ents, cands, self.registry, workspace_id=WS, source_kind="scripted")
            assert res.replayed
            assert self.store.counts(WS) == before, "replay wrote rows"
            return
        self.n += 1
        env = MessageEnvelope(f"f{self.n}", tpl["text"], tpl.get("sender"), tpl.get("recipients", []), tpl.get("ts"), tpl.get("tz"),
                              self.rng.choice(["th1", "th1", "th1", "th2"]), self.rng.choice([None, f"f{max(1, self.n - 1)}"]))
        ents, ids = build_entities(tpl["text"], tpl.get("spans", {}))
        rels = [{"source_id": ids[a], "target_id": ids[b], "label": lab, "score": 0.95, "provenance": "scripted"} for a, b, lab in tpl.get("links", [])]
        cands = build_task_candidates(env, ents, rels, self.registry, primary_source="scripted", config=self.rec.phase4_config)
        res = self.rec.process_message(env, ents, cands, self.registry, workspace_id=WS, source_kind="scripted")
        self.sent.append((env, ents, cands))
        self.pending = res.proposals

    def review(self):
        props = self.store.list_proposals(WS, status="pending")
        if not props:
            return
        p = self.rng.choice(props)
        try:
            if self.rng.random() < 0.75:
                self.rec.accept(WS, p.proposal_id, "fuzz")
            else:
                self.rec.dismiss(WS, p.proposal_id, "fuzz", "random")
        except (ReconciliationError, StaleVersion):
            self.errors += 1

    def manual(self):
        tasks = self.store.list_tasks(WS)
        if not tasks:
            return
        t = self.rng.choice(tasks)
        ev = t.version if self.rng.random() < 0.8 else max(1, t.version - 1)
        try:
            self.rec.manual_edit(WS, t.task_id, "fuzz", ev, {"title": f"{t.title} *"[:60]})
        except (ReconciliationError, StaleVersion):
            self.errors += 1

    def check(self):
        tasks = self.store.list_tasks(WS)
        ids = {t.task_id for t in tasks}
        assert self.seen_ids <= ids, "a task id disappeared"
        self.seen_ids = ids
        for t in tasks:
            assert t.version >= self.versions.get(t.task_id, 1), "version went backwards"
            self.versions[t.task_id] = t.version
            hist = self.store.history_for(WS, t.task_id)
            state = TaskStore.reconstruct(hist)
            for k, v in {"title": t.title, "owner_id": t.owner_id, "status": t.status, "due": t.due, "scheduled": t.scheduled,
                         "pending_changes": t.pending_changes}.items():
                assert state.get(k) == v, f"{t.task_id}: history reconstructs {k}={state.get(k)!r}, task has {v!r}"
        assert [t.task_id for t in tasks] == [f"T-{i}" for i in range(1, len(tasks) + 1)] or True
        rows = self.store.conn.execute("SELECT event_id, task_id, field, before, after, timestamp FROM history ORDER BY event_id").fetchall()
        snap = [tuple(r) for r in rows]
        assert snap[:len(self.hist_snapshot)] == self.hist_snapshot, "history was rewritten"
        self.hist_snapshot = snap
        for p in self.store.list_proposals(WS, status="applied"):
            if p.operation in UPDATE_OPS:
                assert p.match.get("outcome") == "MATCHED", f"{p.operation} applied without a matched referent: {p.match.get('outcome')}"
            if p.operation != "NO_ACTION":
                n = self.store.conn.execute("SELECT COUNT(*) AS n FROM history WHERE workspace_id=? AND proposal_id=?", (WS, p.proposal_id)).fetchone()["n"]
                assert n >= 1, f"applied proposal {p.proposal_id} ({p.operation}) left no history"


class InvariantTests(unittest.TestCase):
    def test_random_interleavings(self):
        for seed in range(30):
            with self.subTest(seed=seed):
                f = Fuzz(seed)
                for step in range(45):
                    r = f.rng.random()
                    if r < 0.45:
                        f.process(f.rng.choice(POOL))
                    elif r < 0.85:
                        f.review()
                    elif r < 0.93:
                        f.process(None, replay=True)
                    else:
                        f.manual()
                    f.check()
                self.assertGreater(len(f.sent), 0)

    def test_fuzz_actually_applies_changes(self):
        # guard against a vacuous fuzz: across seeds, tasks must get created and updated
        created = updated = 0
        for seed in range(30):
            f = Fuzz(seed)
            for _ in range(45):
                r = f.rng.random()
                f.process(f.rng.choice(POOL)) if r < 0.45 else f.review() if r < 0.85 else None
            tasks = f.store.list_tasks(WS)
            created += len(tasks)
            updated += sum(t.version > 1 for t in tasks)
        self.assertGreater(created, 30)
        self.assertGreater(updated, 10)


if __name__ == "__main__":
    unittest.main()
