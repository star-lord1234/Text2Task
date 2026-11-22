import unittest

from src.graph.graph_builder import WorkflowGraph, make_edge_id
from src.graph.graph_editor import GraphEditor
from src.reconciliation.models import ReconciliationError, Task
from src.reconciliation.store import TaskStore


def clock():
    n = {"i": 0}

    def c():
        n["i"] += 1
        return f"2026-11-11T00:00:{n['i']:02d}+00:00"
    return c


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.s = TaskStore(":memory:", clock=clock())
        with self.s.transaction():
            for i in range(4):
                self.s.insert_task(Task(self.s.next_task_id("w"), "w", "th", f"t{i}"))
        self.e = GraphEditor(self.s)

    def test_add_writes_edge_and_history_on_the_dependent(self):
        r = self.e.add_dependency("w", "T-1", "T-2", "riya", evidence="after the draft", source_message_id="m1")
        self.assertEqual((r["status"], r["code"], r["applied"]), ("accepted", "OK", True))
        (h,) = [x for x in self.s.history_for("w", "T-2") if x.operation == "ADD_DEPENDENCY"]
        self.assertEqual((h.actor, h.source_kind, h.field, h.after["status"]), ("riya", "human", "dependency", "accepted"))
        self.assertEqual(self.s.list_dependencies("w")[0].source_kind, "human")

    def test_cycle_attempt_is_stored_held_with_path_and_history(self):
        self.e.add_dependency("w", "T-1", "T-2", "riya")
        r = self.e.add_dependency("w", "T-2", "T-1", "riya")
        self.assertEqual((r["status"], r["code"], r["cycle_path"]), ("rejected", "CYCLE", ["T-2", "T-1", "T-2"]))
        g = WorkflowGraph.from_store(self.s, "w")
        self.assertTrue(g.acyclic)
        self.assertEqual(len(g.held()), 1)
        self.assertTrue(g.held()[0].reason.startswith("CYCLE:"))
        self.assertEqual(len([x for x in self.s.history_for("w", "T-1") if x.operation == "ADD_DEPENDENCY"]), 1)

    def test_duplicate_is_a_no_op(self):
        self.e.add_dependency("w", "T-1", "T-2", "riya")
        n = self.s.counts("w")["history"]
        r = self.e.add_dependency("w", "T-1", "T-2", "dev")
        self.assertEqual((r["applied"], r["code"]), (False, "DUPLICATE"))
        self.assertEqual(self.s.counts("w")["history"], n)

    def test_idempotency_key(self):
        a = self.e.add_dependency("w", "T-1", "T-2", "riya", idempotency_key="k")
        b = self.e.add_dependency("w", "T-1", "T-2", "riya", idempotency_key="k")
        self.assertTrue(b["replayed"])
        self.assertEqual(a["edge_id"], b["edge_id"])
        self.assertEqual(self.s.counts("w")["dependencies"], 1)

    def test_remove_keeps_the_row_and_second_remove_is_noop(self):
        r = self.e.add_dependency("w", "T-1", "T-2", "riya")
        out = self.e.remove_dependency("w", r["edge_id"], "dev", "not needed")
        self.assertTrue(out["applied"])
        (edge,) = self.s.list_dependencies("w")
        self.assertEqual((edge.status, edge.reason), ("rejected", "REMOVED: by dev (not needed)"))
        self.assertFalse(self.e.remove_dependency("w", r["edge_id"], "dev")["applied"])
        with self.assertRaises(ReconciliationError):
            self.e.remove_dependency("w", "E-missing", "dev")

    def test_unknown_endpoint_is_stored_rejected_without_history(self):
        r = self.e.add_dependency("w", "T-1", "T-9", "riya")
        self.assertEqual((r["status"], r["code"]), ("rejected", "UNKNOWN_ENDPOINT"))
        self.assertIsNone(r["history_event_id"])
        self.assertEqual(self.s.counts("w")["dependencies"], 1)

    def test_reconsider_after_the_blocking_edge_is_removed(self):
        a = self.e.add_dependency("w", "T-1", "T-2", "riya")
        self.e.add_dependency("w", "T-2", "T-1", "riya")
        stuck = self.e.reconsider("w", make_edge_id("w", "T-1", "T-2"), "riya")
        self.assertEqual(stuck["status"], "rejected")
        self.e.remove_dependency("w", a["edge_id"], "riya")
        ok = self.e.reconsider("w", make_edge_id("w", "T-1", "T-2"), "riya")
        self.assertEqual((ok["status"], ok["code"]), ("accepted", "OK"))
        self.assertTrue(WorkflowGraph.from_store(self.s, "w").acyclic)

    def test_failure_rolls_back_everything(self):
        from src.graph.graph_constraints import EdgeDecision

        def boom(graph, pre, dep):
            raise RuntimeError("validator exploded")
        before = self.s.counts("w")
        with self.assertRaises(RuntimeError):
            GraphEditor(self.s, boom).add_dependency("w", "T-1", "T-2", "riya")
        self.assertEqual(self.s.counts("w"), before)


if __name__ == "__main__":
    unittest.main()
