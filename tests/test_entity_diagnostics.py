import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EntityDiagnosticTests(unittest.TestCase):
    def test_corrected_annotations_are_separate_and_still_silver(self):
        path = ROOT / "data/diagnostics/entity_pipeline/audit30_corrected_silver_v2.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        self.assertEqual(30, len(rows))
        for row in rows:
            self.assertIn("original_silver_annotations", row)
            corrected = row["corrected_silver_v2_diagnostic"]
            self.assertEqual("SILVER", corrected["annotation_tier"])
            self.assertFalse(corrected["human_verified"])
            for entity in corrected["entities"]:
                self.assertEqual(entity["text"], row["text"][entity["start"]:entity["end"]])

    def test_diagnostic_set_is_single_layer_three_entity_types(self):
        path = ROOT / "data/diagnostics/entity_pipeline/three_class_20_model_ready.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        self.assertEqual(20, len(rows))
        self.assertEqual(20, len({row["source_record_id"] for row in rows}))
        allowed = {"TASK", "PERSON", "TEMPORAL"}
        for row in rows:
            self.assertEqual(1, row["layer_count"])
            self.assertEqual(0, row["layer_index"])
            self.assertTrue({entity["type"] for entity in row["entities"]} <= allowed)

    def test_audit_confirms_distinct_markers_and_mapping(self):
        summary = json.loads((ROOT / "data/diagnostics/entity_pipeline/audit_summary.json").read_text())
        evidence = summary["pipeline_evidence"]
        self.assertTrue(evidence["inputs_distinct_after_marker"])
        self.assertTrue(evidence["mapping_matches_model"])
        self.assertEqual(0, evidence["predicted_b"])


if __name__ == "__main__":
    unittest.main()
