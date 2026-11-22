import json
import unittest

from src.graph.graph_builder import EdgeRecord, WorkflowGraph
from src.graph.serialize import to_dot, to_frontend, to_mermaid
from src.reconciliation.models import Task


def sample():
    ts = {"T-1": Task("T-1", "w", "th", "draft", owner_id="bianca", status="completed", due={"raw": "Fri", "status": "RESOLVED", "value": "2026-11-13"}),
          "T-2": Task("T-2", "w", "th", 'review "it"', owner_id="dev"), "T-3": Task("T-3", "w", "th", "ship", owner_id="riya")}
    es = [EdgeRecord("E2", "T-2", "T-3", "accepted", "after review", "m2", "rule", 0.9), EdgeRecord("E1", "T-1", "T-2", "accepted", "after draft", "m1", "human"),
          EdgeRecord("E3", "T-3", "T-1", "rejected", reason="CYCLE: T-3 -> T-1 -> T-2 -> T-3"), EdgeRecord("E4", "T-1", "T-3", "proposed"),
          EdgeRecord("E5", "T-1", "T-99", "rejected", reason="UNKNOWN_ENDPOINT: ...")]
    return WorkflowGraph("w", ts, es)


class SerializeTests(unittest.TestCase):
    def test_contract_shape(self):
        d = to_frontend(sample())
        self.assertEqual({"nodes", "edges", "meta"}, set(d))
        n = d["nodes"][1]
        for k in ("id", "title", "owner_id", "status", "derived_state", "blocked_by", "cancelled_prereqs", "root_blockers", "due", "layer", "source_message_id", "version"):
            self.assertIn(k, n)
        e = d["edges"][0]
        for k in ("id", "source", "target", "kind", "evidence", "source_message_id", "source_kind", "score", "reason", "warnings", "redundant", "dangling"):
            self.assertIn(k, e)
        self.assertEqual(d["meta"]["schema"], "phase6-v1")

    def test_direction_kinds_and_states(self):
        d = to_frontend(sample())
        by_id = {e["id"]: e for e in d["edges"]}
        self.assertEqual((by_id["E1"]["source"], by_id["E1"]["target"], by_id["E1"]["kind"]), ("T-1", "T-2", "accepted"))
        self.assertEqual(by_id["E3"]["kind"], "held")
        self.assertEqual(by_id["E4"]["kind"], "proposed")
        self.assertTrue(by_id["E5"]["dangling"])
        states = {n["id"]: n["derived_state"] for n in d["nodes"]}
        self.assertEqual(states, {"T-1": "done", "T-2": "ready", "T-3": "blocked"})
        self.assertEqual((d["meta"]["ready"], d["meta"]["blocked"], d["meta"]["held_edges"], d["meta"]["proposed_edges"]), (["T-2"], ["T-3"], 2, 1))

    def test_deterministic_sorted_and_json_serialisable(self):
        a, b = json.dumps(to_frontend(sample()), sort_keys=True), json.dumps(to_frontend(sample()), sort_keys=True)
        self.assertEqual(a, b)
        # edges sorted by (prerequisite, dependent, id) with numeric task order: T-1 -> {T-2, T-3, T-99}, T-2 -> T-3, T-3 -> T-1
        self.assertEqual([e["id"] for e in to_frontend(sample())["edges"]], ["E1", "E4", "E5", "E2", "E3"])
        self.assertEqual([n["id"] for n in to_frontend(sample())["nodes"]], ["T-1", "T-2", "T-3"])

    def test_warning_objects_carry_severity(self):
        g = sample()
        g.get_edge("T-1", "T-3").warnings = ["REDUNDANT_TRANSITIVE"]
        e = [x for x in to_frontend(g)["edges"] if x["id"] == "E4"][0]
        self.assertEqual(e["warnings"][0]["code"], "REDUNDANT_TRANSITIVE")
        self.assertEqual(e["warnings"][0]["severity"], "info")

    def test_dot_and_mermaid_text(self):
        g = sample()
        dot, mmd = to_dot(g), to_mermaid(g)
        self.assertIn('"T-1" -> "T-2" [style=solid]', dot)
        self.assertIn("style=dotted, color=red", dot)
        self.assertIn("T_1 --> T_2", mmd)
        self.assertIn("-.->", mmd)
        self.assertIn("held: CYCLE", mmd)
        self.assertNotIn("T_99", mmd)                    # dangling edge not drawn
        self.assertTrue(dot.endswith("}\n"))


if __name__ == "__main__":
    unittest.main()
