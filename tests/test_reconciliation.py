import json
import unittest
from pathlib import Path

from src.reconciliation.scenario_runner import run_scenario

FX = Path(__file__).parent / "fixtures"
SCENARIOS = json.loads((FX / "reconciliation_scenarios.json").read_text())["scenarios"]
EXTENSIONS = json.loads((FX / "reconciliation_scenarios_ext.json").read_text())["scenarios"]


class ScenarioTests(unittest.TestCase):
    def test_all_scenarios(self):
        for sc in SCENARIOS:
            with self.subTest(scenario=sc["name"]):
                r = run_scenario(sc)
                self.assertEqual(r["failures"], [], "\n".join(r["failures"]))


class ExtensionScenarioTests(unittest.TestCase):
    """Positive AND negative regression scenarios for the four extensions (ack, prerequisite clause, 'is ready', 'I'll begin')."""

    def test_extension_scenarios(self):
        for sc in EXTENSIONS:
            with self.subTest(scenario=sc["name"]):
                r = run_scenario(sc)
                self.assertEqual(r["failures"], [], "\n".join(r["failures"]))

    def test_extensions_have_both_positive_and_negative_cases(self):
        names = [s["name"] for s in EXTENSIONS]
        self.assertGreaterEqual(sum("neg" in n for n in names), 8)
        self.assertGreaterEqual(len(names) - sum("neg" in n for n in names), 8)


if __name__ == "__main__":
    unittest.main()
