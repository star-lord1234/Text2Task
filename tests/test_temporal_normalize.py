import json
import re
import unittest
from pathlib import Path

from src.temporal.normalize import normalize_temporal

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "temporal_cases.json").read_text())["cases"]
SOURCE = (Path(__file__).resolve().parents[1] / "src" / "temporal" / "normalize.py").read_text()


class TemporalFixtureTests(unittest.TestCase):
    def test_fixture_cases(self):
        for case in FIXTURES:
            with self.subTest(raw=case["raw"], ref=case["ref"], tz=case["tz"]):
                tv = normalize_temporal(case["raw"], reference_ts=case["ref"], timezone=case["tz"])
                exp = case["expect"]
                self.assertEqual(tv.status, exp["status"], tv.to_dict())
                for key in ("granularity", "value", "start", "end", "part_of_day", "in_past", "deadline_phrase"):
                    if key in exp:
                        self.assertEqual(getattr(tv, key), exp[key], (key, tv.to_dict()))
                for a in exp.get("assumptions_include", []):
                    self.assertIn(a, tv.assumptions, tv.to_dict())
                for a in exp.get("assumptions_exclude", []):
                    self.assertNotIn(a, tv.assumptions, tv.to_dict())
                if "candidate_dates" in exp:
                    self.assertEqual(sorted(c["date"] for c in tv.candidates), sorted(exp["candidate_dates"]))
                self.assertEqual(tv.raw, case["raw"])  # raw preserved

    def test_never_reads_machine_clock(self):
        self.assertIsNone(re.search(r"\.now\(|\.today\(|\.utcnow\(|time\.time\(", SOURCE))
        tv = normalize_temporal("Friday")
        self.assertEqual(tv.status, "UNRESOLVED_NO_ANCHOR")
        self.assertIsNone(tv.value)

    def test_empty_input(self):
        self.assertEqual(normalize_temporal("").status, "UNPARSEABLE")

    def test_json_roundtrip(self):
        tv = normalize_temporal("Monday at 10", reference_ts="2026-11-11T09:30:00", timezone="America/Chicago")
        self.assertEqual(json.loads(json.dumps(tv.to_dict()))["value"], tv.value)


if __name__ == "__main__":
    unittest.main()
