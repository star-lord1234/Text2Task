import unittest

from src.graph.graph_builder import EdgeRecord, WorkflowGraph
from src.graph.workflow_state import compute_states, diff_states, impact_of
from src.reconciliation.models import Task


def g(statuses, edges):
    ts = {f"T-{i}": Task(f"T-{i}", "w", "th", f"t{i}", status=s) for i, s in enumerate(statuses, 1)}
    return WorkflowGraph("w", ts, [EdgeRecord(f"E{i}", a, b, st) for i, (a, b, st) in enumerate(edges)])


class StateTests(unittest.TestCase):
    def test_basic_states(self):
        s = compute_states(g(["open", "open", "completed", "cancelled"], [("T-1", "T-2", "accepted")]))
        self.assertEqual([s[f"T-{i}"].derived for i in range(1, 5)], ["ready", "blocked", "done", "cancelled"])
        self.assertEqual(s["T-2"].blocked_by, ["T-1"])

    def test_in_progress_prerequisite_still_blocks(self):
        s = compute_states(g(["in_progress", "open"], [("T-1", "T-2", "accepted")]))
        self.assertEqual(s["T-2"].derived, "blocked")
        self.assertEqual(s["T-1"].derived, "ready")      # in-progress tasks with nothing before them are ready (actionable)

    def test_cancelled_prerequisite_does_not_satisfy(self):
        s = compute_states(g(["cancelled", "open"], [("T-1", "T-2", "accepted")]))
        self.assertEqual(s["T-2"].derived, "blocked_cancelled_prereq")
        self.assertEqual(s["T-2"].cancelled_prereqs, ["T-1"])
        self.assertEqual(s["T-2"].blocked_by, [])

    def test_incomplete_prerequisite_takes_precedence_over_cancelled(self):
        s = compute_states(g(["cancelled", "open", "open"], [("T-1", "T-3", "accepted"), ("T-2", "T-3", "accepted")]))
        self.assertEqual((s["T-3"].derived, s["T-3"].blocked_by, s["T-3"].cancelled_prereqs), ("blocked", ["T-2"], ["T-1"]))

    def test_proposed_and_held_edges_never_block(self):
        s = compute_states(g(["open", "open", "open"], [("T-1", "T-2", "proposed"), ("T-3", "T-2", "rejected")]))
        self.assertEqual(s["T-2"].derived, "ready")

    def test_root_blockers_include_stuck_cancelled_branches(self):
        s = compute_states(g(["cancelled", "open", "open"], [("T-1", "T-2", "accepted"), ("T-2", "T-3", "accepted")]))
        self.assertEqual(s["T-2"].derived, "blocked_cancelled_prereq")
        self.assertEqual(s["T-3"].root_blockers, ["T-2"])

    def test_diff_and_impact(self):
        graph = g(["open", "open", "open"], [("T-1", "T-2", "accepted"), ("T-2", "T-3", "accepted")])
        d = impact_of(graph, "T-1", "completed")
        self.assertEqual((d.became_ready, d.became_done, d.became_blocked), (["T-2"], ["T-1"], []))
        self.assertEqual(d.changed["T-2"], ("blocked", "ready"))
        self.assertEqual(graph.tasks["T-1"].status, "open")             # pure what-if
        d2 = impact_of(graph, "T-1", "cancelled")
        self.assertEqual((d2.became_review, d2.became_ready), (["T-2"], []))
        self.assertEqual(diff_states(compute_states(graph), compute_states(graph)).changed, {})

    def test_empty_graph(self):
        self.assertEqual(compute_states(WorkflowGraph("w", {}, [])), {})


if __name__ == "__main__":
    unittest.main()
