import json
import unittest
from pathlib import Path

from src.graph.graph_constraints import make_dependency_validator
from src.graph.graph_builder import WorkflowGraph
from src.graph.scenario_runner import run_graph_scenario
from src.reconciliation.reconciler import Reconciler
from src.reconciliation.scenario_runner import run_scenario
from src.reconciliation.store import TaskStore

FX = Path(__file__).parent / "fixtures"
GRAPH = json.loads((FX / "graph_scenarios.json").read_text())["scenarios"]
PARTS = [{"id": "riya", "display_name": "Riya Sharma", "aliases": ["Riya"]}, {"id": "bianca", "display_name": "Bianca Sawant", "aliases": ["Bianca"]},
         {"id": "dev", "display_name": "Dev Patel", "aliases": ["Dev"]}]
TS, TZ = "2026-11-11T09:30:00", "America/Chicago"


def create(i, sender, text, task, person, when, rec):
    return {"id": f"m{i}", "sender": sender, "text": text, "recipients": rec, "ts": TS, "tz": TZ,
            "spans": {"TASK": [task], "PERSON": [person], "TEMPORAL": [when]},
            "links": [[task, person, "ASSIGNED_TO"], [task, when, "DUE_ON"]], "review": [{"accept": "all"}], "expect": {"ops": ["CREATE_TASK"]}}


def dep(i, text, accept=True):
    return {"id": f"m{i}", "sender": "riya", "text": text, "recipients": ["bianca"], "ts": TS, "tz": TZ, "spans": {}, "links": [],
            "review": [{"accept": "all"}] if accept else [], "expect": {"ops": ["ADD_DEPENDENCY"]}}


CHAT_CYCLE = {"name": "chat_cycle", "participants": PARTS, "messages": [
    create(1, "riya", "Bianca, send the notes by Friday.", "send the notes", "Bianca", "Friday", ["bianca"]),
    create(2, "riya", "Dev, approve the draft by Thursday.", "approve the draft", "Dev", "Thursday", ["dev"]),
    create(3, "riya", "Dev, book the room by Friday.", "book the room", "Dev", "Friday", ["dev"]),
    dep(4, "The notes are waiting on the draft."), dep(5, "The draft is waiting on the room."), dep(6, "The room is waiting on the notes.")]}


class GraphScenarioTests(unittest.TestCase):
    def test_all_graph_scenarios(self):
        for sc in GRAPH:
            with self.subTest(scenario=sc["name"]):
                r = run_graph_scenario(sc)
                self.assertEqual(r["failures"], [], "\n".join(r["failures"]))

    def test_chat_derived_cycle_is_held_by_the_real_validator(self):
        rec = Reconciler(TaskStore(":memory:"), dependency_validator=make_dependency_validator())
        r = run_scenario(CHAT_CYCLE, reconciler=rec)
        self.assertEqual(r["failures"], [])
        deps = {(d.dependent_task_id, d.prerequisite_task_id): d for d in rec.store.list_dependencies("w")}
        self.assertEqual(deps[("T-1", "T-2")].status, "accepted")
        self.assertEqual(deps[("T-2", "T-3")].status, "accepted")
        held = deps[("T-3", "T-1")]
        self.assertEqual(held.status, "rejected")                 # kept, with its reason, never silently dropped
        self.assertTrue(held.reason.startswith("CYCLE:"), held.reason)
        g = WorkflowGraph.from_store(rec.store, "w")
        self.assertTrue(g.acyclic)
        self.assertEqual(g.topological_order(), ["T-3", "T-2", "T-1"])   # T-1 waits on T-2 waits on T-3

    def test_placeholder_validator_would_accept_the_cycle_and_the_snapshot_reports_it(self):
        rec = Reconciler(TaskStore(":memory:"))                   # Phase 5 default validator: no cycle check
        r = run_scenario(CHAT_CYCLE, reconciler=rec)
        self.assertEqual(r["failures"], [])
        g = WorkflowGraph.from_store(rec.store, "w")
        self.assertFalse(g.acyclic)                               # integrity problem is surfaced, not hidden
        self.assertIsNone(g.topological_order())
        self.assertEqual(set(g.cycle), {"T-1", "T-2", "T-3"})

    def test_existing_phase5_dependency_scenarios_pass_with_the_graph_validator(self):
        sc5 = json.loads((FX / "reconciliation_scenarios.json").read_text())["scenarios"]
        for sc in sc5:
            if sc["name"].startswith(("32_", "33_", "34_")):
                with self.subTest(scenario=sc["name"]):
                    rec = Reconciler(TaskStore(":memory:"), dependency_validator=make_dependency_validator())
                    r = run_scenario(sc, reconciler=rec)
                    self.assertEqual(r["failures"], [], "\n".join(r["failures"]))


if __name__ == "__main__":
    unittest.main()
