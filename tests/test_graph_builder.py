import unittest

from src.graph.graph_builder import EdgeRecord, WorkflowGraph, make_edge_id
from src.reconciliation.models import DependencyEdge, Task
from src.reconciliation.store import TaskStore


def tasks(n=4, **status):
    return {f"T-{i}": Task(f"T-{i}", "w", "th", f"task {i}", status=status.get(f"T-{i}", "open")) for i in range(1, n + 1)}


def edge(a, b, status="accepted", **k):
    return EdgeRecord(f"E-{a}{b}", a, b, status, **k)


class BuilderTests(unittest.TestCase):
    def test_direction_prerequisite_to_dependent(self):
        g = WorkflowGraph("w", tasks(), [edge("T-1", "T-2")])
        self.assertTrue(g.strict.has_edge("T-1", "T-2"))
        self.assertFalse(g.strict.has_edge("T-2", "T-1"))
        self.assertEqual(g.prerequisites_of("T-2"), ["T-1"])
        self.assertEqual(g.dependents_of("T-1"), ["T-2"])

    def test_only_accepted_edges_enter_the_strict_graph(self):
        g = WorkflowGraph("w", tasks(), [edge("T-1", "T-2"), edge("T-2", "T-3", "proposed"), edge("T-3", "T-4", "rejected")])
        self.assertEqual(list(g.strict.edges), [("T-1", "T-2")])
        self.assertEqual((len(g.accepted()), len(g.proposed()), len(g.held())), (1, 1, 1))
        self.assertEqual([e.kind for e in g.edges], ["accepted", "proposed", "held"])

    def test_order_layers_and_queries(self):
        g = WorkflowGraph("w", tasks(), [edge("T-1", "T-2"), edge("T-2", "T-3"), edge("T-1", "T-4")])
        self.assertEqual(g.topological_order(), ["T-1", "T-2", "T-3", "T-4"])
        self.assertEqual(g.layers(), {"T-1": 0, "T-2": 1, "T-3": 2, "T-4": 1})
        self.assertEqual(g.ancestors_of("T-3"), ["T-1", "T-2"])
        self.assertEqual(g.descendants_of("T-1"), ["T-2", "T-3", "T-4"])
        self.assertEqual(g.longest_chain(), ["T-1", "T-2", "T-3"])

    def test_stored_cycle_is_reported_not_hidden_and_does_not_crash(self):
        g = WorkflowGraph("w", tasks(3), [edge("T-1", "T-2"), edge("T-2", "T-3"), edge("T-3", "T-1")])
        self.assertFalse(g.acyclic)
        self.assertEqual(set(g.cycle), {"T-1", "T-2", "T-3"})
        self.assertIsNone(g.topological_order())
        self.assertIsNone(g.layers())
        self.assertFalse(g.integrity["acyclic"])

    def test_dangling_edges_are_flagged_and_excluded(self):
        g = WorkflowGraph("w", tasks(2), [edge("T-1", "T-9")])
        self.assertTrue(g.edges[0].dangling)
        self.assertEqual(g.integrity["dangling_edges"], ["E-T-1T-9"])
        self.assertEqual(g.strict.number_of_edges(), 0)

    def test_with_task_status_is_a_copy(self):
        g = WorkflowGraph("w", tasks(), [edge("T-1", "T-2")])
        g2 = g.with_task_status("T-1", "completed")
        self.assertEqual(g.tasks["T-1"].status, "open")
        self.assertEqual(g2.tasks["T-1"].status, "completed")
        self.assertIsNot(g.strict, g2.strict)

    def test_deterministic_regardless_of_input_order(self):
        e = [edge("T-1", "T-2"), edge("T-2", "T-3"), edge("T-1", "T-3")]
        a = WorkflowGraph("w", tasks(3), e)
        b = WorkflowGraph("w", dict(reversed(list(tasks(3).items()))), list(reversed(e)))
        self.assertEqual([x.edge_id for x in a.edges], [x.edge_id for x in b.edges])
        self.assertEqual(a.topological_order(), b.topological_order())

    def test_from_store_roundtrip_and_phase5_edge_ids(self):
        s = TaskStore(":memory:")
        with s.transaction():
            for i in (1, 2):
                s.insert_task(Task(s.next_task_id("w"), "w", "th", f"task {i}"))
            s.insert_dependency(DependencyEdge(make_edge_id("w", "T-2", "T-1"), "w", "T-2", "T-1", "accepted", "after A", "m1", "rule"))
        g = WorkflowGraph.from_store(s, "w")
        (e,) = g.edges
        self.assertEqual((e.prerequisite, e.dependent, e.status, e.evidence), ("T-1", "T-2", "accepted", "after A"))

    def test_edge_id_matches_phase5_formula(self):
        from src.reconciliation.reconciler import _h
        self.assertEqual(make_edge_id("w", "T-2", "T-1"), "E-" + _h("w", "T-2", "T-1"))


if __name__ == "__main__":
    unittest.main()
