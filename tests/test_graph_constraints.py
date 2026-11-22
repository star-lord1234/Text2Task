import itertools
import random
import unittest

from src.graph.graph_builder import EdgeRecord, WorkflowGraph
from src.graph.graph_constraints import (baseline_greedy_select, e5_select, edge_warnings, make_dependency_validator, milp_optimum,
                                         validate_new_edge)
from src.reconciliation.models import Task


def due(v):
    return {"raw": v, "status": "RESOLVED", "value": v, "start": v, "end": v}


def graph(edges, n=4, **kw):
    ts = {f"T-{i}": Task(f"T-{i}", "w", "th", f"t{i}", **kw.get(f"T-{i}", {})) for i in range(1, n + 1)}
    return WorkflowGraph("w", ts, [EdgeRecord(f"E{i}", a, b, "accepted") for i, (a, b) in enumerate(edges)])


class ValidationTests(unittest.TestCase):
    def test_structural_rejections(self):
        g = graph([("T-1", "T-2"), ("T-2", "T-3")])
        self.assertEqual(validate_new_edge(g, "T-1", "T-1").code, "SELF")
        self.assertEqual(validate_new_edge(g, "T-1", "T-9").code, "UNKNOWN_ENDPOINT")
        self.assertEqual(validate_new_edge(g, "T-1", "T-2").code, "DUPLICATE")
        d = validate_new_edge(g, "T-3", "T-1")
        self.assertEqual((d.accepted, d.code), (False, "CYCLE"))
        self.assertEqual(d.cycle_path, ["T-3", "T-1", "T-2", "T-3"])
        self.assertIn("T-3 -> T-1 -> T-2 -> T-3", d.reason)
        self.assertTrue(validate_new_edge(g, "T-1", "T-4").accepted)

    def test_cancelled_prerequisite_and_inconsistent_completion_warn(self):
        g = graph([], **{"T-1": {"status": "cancelled"}, "T-2": {"status": "completed"}, "T-3": {"status": "open"}})
        self.assertEqual(validate_new_edge(g, "T-1", "T-4").warnings, ["PREREQUISITE_CANCELLED"])
        self.assertEqual(validate_new_edge(g, "T-3", "T-2").warnings, ["INCONSISTENT_COMPLETION"])
        self.assertEqual(validate_new_edge(g, "T-1", "T-2").warnings, ["PREREQUISITE_CANCELLED"])   # completed prerequisite+cancelled: only cancel

    def test_timing_warning_needs_both_resolved_dates(self):
        g = graph([], **{"T-1": {"due": due("2026-11-20")}, "T-2": {"due": due("2026-11-13")},
                         "T-3": {"due": {"raw": "after approval", "status": "UNRESOLVED_EVENT_CONDITION", "value": None}}})
        self.assertEqual(validate_new_edge(g, "T-1", "T-2").warnings, ["PREREQUISITE_DUE_AFTER_DEPENDENT"])
        self.assertEqual(validate_new_edge(g, "T-2", "T-1").warnings, [])
        self.assertEqual(validate_new_edge(g, "T-3", "T-2").warnings, [])      # unresolved: never compared
        self.assertEqual(validate_new_edge(g, "T-4", "T-1").warnings, [])      # missing date: never compared

    def test_redundant_edge_warning(self):
        g = graph([("T-1", "T-2"), ("T-2", "T-3")])
        self.assertEqual(validate_new_edge(g, "T-1", "T-3").warnings, ["REDUNDANT_TRANSITIVE"])
        self.assertEqual(validate_new_edge(g, "T-1", "T-4").warnings, [])

    def test_validator_callable_for_phase5(self):
        from src.reconciliation.models import Task as T
        from src.reconciliation.store import TaskStore
        s = TaskStore(":memory:")
        with s.transaction():
            for i in range(3):
                s.insert_task(T(s.next_task_id("w"), "w", "th", f"t{i}"))
        v = make_dependency_validator()
        self.assertEqual(v(s, "w", "T-2", "T-1"), (True, ""))
        ok, reason = v(s, "w", "T-1", "T-1")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("SELF:"))


class E5Tests(unittest.TestCase):
    def test_fixed_edges_are_never_dropped_and_forced_out_edges_are_reported(self):
        r = e5_select([("b", "a", 0.9), ("c", "d", 0.4)], fixed=[("a", "b")])
        self.assertEqual([(u, v) for u, v, _ in r["kept"]], [("c", "d")])
        self.assertIn(("b", "a"), [(u, v) for u, v, _ in r["dropped"]])

    def test_drops_the_lowest_score_edge_of_a_cycle(self):
        r = e5_select([("a", "b", 0.9), ("b", "c", 0.8), ("c", "a", 0.3)])
        self.assertEqual({(u, v) for u, v, _ in r["kept"]}, {("a", "b"), ("b", "c")})
        self.assertEqual(r["components"][0]["method"], "exact")

    def test_exact_matches_milp_optimum_and_greedy_is_never_better(self):
        rng = random.Random(7)
        greedy_worse = 0
        for _ in range(60):
            nodes = "abcdef"[: rng.randint(3, 6)]
            pairs = [(u, v) for u in nodes for v in nodes if u != v]
            cand = [(u, v, round(rng.uniform(0.1, 1.0), 2)) for u, v in rng.sample(pairs, min(len(pairs), rng.randint(4, 9)))]
            e5 = e5_select(cand)
            total = sum(w for *_, w in e5["kept"])
            self.assertTrue(_acyclic([(u, v) for u, v, _ in e5["kept"]]))
            self.assertAlmostEqual(total, milp_optimum(cand), places=6)
            g = sum(w for *_, w in baseline_greedy_select(cand))
            self.assertLessEqual(g, total + 1e-9)
            greedy_worse += g < total - 1e-9
        self.assertGreater(greedy_worse, 0)     # E5 genuinely differs from order-dependent acceptance on some inputs

    def test_empty_and_self_loop_only_candidates(self):
        self.assertEqual(milp_optimum([]), 0.0)
        self.assertEqual(milp_optimum([("a", "a", 0.9)]), 0.0)
        self.assertEqual(e5_select([])["kept"], [])
        self.assertEqual(e5_select([("a", "a", 0.9)])["kept"], [])

    def test_greedy_fallback_for_large_components_is_acyclic(self):
        rng = random.Random(3)
        nodes = [f"n{i}" for i in range(9)]
        cand = [(u, v, round(rng.uniform(0.1, 1), 2)) for u in nodes for v in nodes if u != v and rng.random() < 0.5]
        r = e5_select(cand, exact_max_edges=4)
        self.assertTrue(_acyclic([(u, v) for u, v, _ in r["kept"]]))
        self.assertTrue(any(c["method"] == "greedy" for c in r["components"]))


def _acyclic(edges):
    import networkx as nx
    g = nx.DiGraph(); g.add_edges_from(edges)
    return nx.is_directed_acyclic_graph(g)


if __name__ == "__main__":
    unittest.main()
