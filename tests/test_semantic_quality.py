import unittest

from scripts.annotate_entities_v2 import normalize_prediction
from src.annotation.semantic_quality import semantic_quality


def task(entity_id, text, start=0, operation="CREATE", status="PENDING"):
    return {
        "id": entity_id, "type": "TASK", "start": start, "end": start + len(text), "text": text,
        "task_attributes": {"operation": operation, "status": status, "identity_status": "LOCAL_ONLY"},
    }


class SemanticQualityTests(unittest.TestCase):
    def record(self, text, entities):
        return {"text": text, "text2task_annotations": {"entities": entities}}

    def test_historical_event_is_severe(self):
        result = semantic_quality(self.record("The lawsuit was filed", [task("e1", "The lawsuit was filed")]))
        self.assertFalse(result["passed_for_training"])
        self.assertIn("historical_task", {item["code"] for item in result["warnings"]})

    def test_actionable_request_passes(self):
        result = semantic_quality(self.record("Please send the report", [task("e1", "Please send the report")]))
        self.assertTrue(result["passed_for_training"])

    def test_nested_tasks_are_severe(self):
        text = "Please send the report"
        entities = [task("e1", text), task("e2", "send the report", 7)]
        result = semantic_quality(self.record(text, entities))
        self.assertFalse(result["passed_for_training"])
        self.assertIn("nested_or_overlapping_tasks", {item["code"] for item in result["warnings"]})

    def test_unique_case_only_offset_repair_is_recorded(self):
        entities, corrections, errors = normalize_prediction({
            "entities": [{
                "type": "PERSON", "text": "alice", "start": 99, "end": 104,
                "negated": False, "ambiguous": False,
            }],
            "notes": [],
        }, "Ask Alice tomorrow")
        self.assertEqual([], errors)
        self.assertEqual("Alice", entities[0]["text"])
        self.assertEqual("case_insensitive", corrections[0]["method"])


if __name__ == "__main__":
    unittest.main()
