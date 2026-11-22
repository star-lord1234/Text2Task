import os
import sqlite3
import tempfile
import unittest

from src.reconciliation.models import DependencyEdge, ProposedOperation, StaleVersion, Task
from src.reconciliation.store import TaskStore

WS = "w1"


def fixed_clock():
    n = {"i": 0}

    def clock():
        n["i"] += 1
        return f"2026-01-01T00:00:{n['i']:02d}+00:00"
    return clock


def mk(store, ws=WS, title="prepare the report"):
    tid = store.next_task_id(ws)
    store.insert_task(Task(task_id=tid, workspace_id=ws, thread_id="th", title=title, owner_id="bianca", created_by="riya",
                           created_at=store.now(), due={"raw": "Friday", "status": "RESOLVED", "value": "2026-11-13"}))
    return tid


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.s = TaskStore(":memory:", clock=fixed_clock())

    def test_stable_sequential_ids_per_workspace(self):
        with self.s.transaction():
            a, b, c = mk(self.s), mk(self.s), mk(self.s, ws="other")
        self.assertEqual((a, b, c), ("T-1", "T-2", "T-1"))
        self.assertEqual([t.task_id for t in self.s.list_tasks(WS)], ["T-1", "T-2"])

    def test_roundtrip_preserves_unresolved_fields(self):
        with self.s.transaction():
            tid = self.s.next_task_id(WS)
            self.s.insert_task(Task(tid, WS, "th", "send notes", due={"raw": "after approval", "status": "UNRESOLVED_EVENT_CONDITION", "value": None}))
        t = self.s.get_task(WS, tid)
        self.assertEqual(t.due["status"], "UNRESOLVED_EVENT_CONDITION")
        self.assertIsNone(t.due["value"])
        self.assertIsNone(t.owner_id)

    def test_update_bumps_version_and_checks_it(self):
        with self.s.transaction():
            tid = mk(self.s)
        with self.s.transaction():
            v = self.s.update_task(WS, tid, 1, {"status": "completed"})
        self.assertEqual(v, 2)
        with self.assertRaises(StaleVersion):
            with self.s.transaction():
                self.s.update_task(WS, tid, 1, {"status": "cancelled"})
        self.assertEqual(self.s.get_task(WS, tid).status, "completed")
        self.assertEqual(self.s.get_task(WS, tid).version, 2)

    def test_transaction_rolls_back_everything(self):
        with self.assertRaises(RuntimeError):
            with self.s.transaction():
                mk(self.s)
                self.s.append_history(WS, "T-1", operation="X", field="status", before=None, after="open", actor="a", source_kind="human")
                raise RuntimeError("boom")
        self.assertEqual(self.s.counts(WS)["tasks"], 0)
        self.assertEqual(self.s.counts(WS)["history"], 0)
        with self.s.transaction():
            self.assertEqual(mk(self.s), "T-1")   # the id counter rolled back too

    def test_history_is_append_only(self):
        with self.s.transaction():
            tid = mk(self.s)
            self.s.append_history(WS, tid, operation="CREATE_TASK", field="__create__", before=None, after={"title": "x"}, actor="riya", source_kind="rule")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.conn.execute("UPDATE history SET actor='mallory'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.conn.execute("DELETE FROM history")
        self.assertEqual(len(self.s.history_for(WS, tid)), 1)

    def test_reconstruct_from_history(self):
        with self.s.transaction():
            tid = mk(self.s)
            h = lambda **k: self.s.append_history(WS, tid, operation=k.pop("op"), actor="a", source_kind="rule", **k)
            h(op="CREATE_TASK", field="__create__", before=None, after={"title": "t", "owner_id": "bianca", "status": "open", "due": {"raw": "Friday"}, "scheduled": None})
            h(op="PROPOSE_DUE_DATE_CHANGE", field="pending_due", before=None, after={"raw": "Monday"})
            h(op="CONFIRM_DUE_DATE_CHANGE", field="due", before={"raw": "Friday"}, after={"raw": "Monday"})
            h(op="CONFIRM_DUE_DATE_CHANGE", field="pending_due", before={"raw": "Monday"}, after=None)
            h(op="COMPLETE_TASK", field="status", before="open", after="completed")
        state = TaskStore.reconstruct(self.s.history_for(WS, tid))
        self.assertEqual(state["due"], {"raw": "Monday"})
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["pending_changes"], {})

    def test_proposal_insert_is_idempotent_and_ordered(self):
        p = ProposedOperation(proposal_id="P-1", workspace_id=WS, message_id="m1", operation="NO_ACTION")
        with self.s.transaction():
            self.assertTrue(self.s.insert_proposal(p))
            self.assertFalse(self.s.insert_proposal(p))
        self.assertEqual(len(self.s.list_proposals(WS)), 1)

    def test_processed_messages_ordinal_and_idempotency_keys(self):
        with self.s.transaction():
            self.assertEqual(self.s.mark_processed(WS, "m1", "th", "h1"), 1)
            self.assertEqual(self.s.mark_processed(WS, "m2", "th", "h2"), 2)
            self.assertEqual(self.s.mark_processed(WS, "m3", "other", "h3"), 1)
            self.s.save_idempotent(WS, "k", {"ok": True})
        self.assertEqual(self.s.get_idempotent(WS, "k"), {"ok": True})
        self.assertIsNone(self.s.get_idempotent(WS, "nope"))
        self.assertEqual(self.s.current_seq(WS, "th"), 2)

    def test_dependencies_roundtrip(self):
        with self.s.transaction():
            a, b = mk(self.s), mk(self.s)
            self.s.insert_dependency(DependencyEdge("E-1", WS, b, a, evidence="after A"))
        self.s.set_dependency_status(WS, "E-1", "rejected", "cycle")
        (e,) = self.s.list_dependencies(WS)
        self.assertEqual((e.dependent_task_id, e.prerequisite_task_id, e.status, e.reason), ("T-2", "T-1", "rejected", "cycle"))

    def test_file_database_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.db")
            s1 = TaskStore(path, clock=fixed_clock())
            with s1.transaction():
                mk(s1)
            s1.close()
            s2 = TaskStore(path)
            self.assertEqual(s2.get_task(WS, "T-1").title, "prepare the report")
            with s2.transaction():
                self.assertEqual(mk(s2), "T-2")
            s2.close()


if __name__ == "__main__":
    unittest.main()
