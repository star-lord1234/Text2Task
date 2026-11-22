import copy
import unittest
from pathlib import Path

from src.annotation.validators import (
    assert_valid_record,
    load_schema,
    validate_jsonl,
    validate_record,
    validate_schema_definition,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def task_attributes(**overrides):
    values = {
        "operation": "UPDATE",
        "status": "PENDING",
        "negated": False,
        "ambiguous": False,
        "missing_fields": [],
        "unresolved_fields": [],
        "thread_task_id": None,
        "identity_status": "LOCAL_ONLY",
    }
    values.update(overrides)
    return values


def annotated_record():
    text = "Alice, please update the report by Friday."
    return {
        "id": "mailex:train:example:turn_0000",
        "source": "mailex",
        "source_split": "train",
        "thread_id": "example",
        "turn_index": 0,
        "text": text,
        "text2task_annotations": {
            "schema_version": "1.0.0",
            "annotation_status": "DRAFT",
            "annotator_id": "unit-test",
            "entities": [
                {"id": "e1", "type": "PERSON", "start": 0, "end": 5, "text": "Alice", "task_attributes": None},
                {
                    "id": "e2",
                    "type": "TASK",
                    "start": 14,
                    "end": 31,
                    "text": "update the report",
                    "task_attributes": task_attributes(),
                },
                {"id": "e3", "type": "ARTIFACT", "start": 25, "end": 31, "text": "report", "task_attributes": None},
                {"id": "e4", "type": "TEMPORAL", "start": 35, "end": 41, "text": "Friday", "task_attributes": None},
            ],
            "relations": [
                {
                    "id": "r1",
                    "type": "ASSIGNED_TO",
                    "source_entity_id": "e2",
                    "target_entity_id": "e1",
                    "relation_evidence": {"start": 0, "end": 31, "text": "Alice, please update the report"},
                    "explicit_vs_inferred": "EXPLICIT",
                    "ambiguous": False,
                },
                {
                    "id": "r2",
                    "type": "DUE_ON",
                    "source_entity_id": "e2",
                    "target_entity_id": "e4",
                    "relation_evidence": {"start": 32, "end": 41, "text": "by Friday"},
                    "explicit_vs_inferred": "EXPLICIT",
                    "ambiguous": False,
                },
            ],
            "relation_candidates": [
                {
                    "id": "rc1",
                    "source_entity_id": "e2",
                    "target_entity_id": "e3",
                    "label": "NONE",
                    "relation_evidence": None,
                    "explicit_vs_inferred": None,
                }
            ],
            "reference_resolution": {
                "status": "DEFERRED_NO_REFERENCE_SPANS",
                "mentions": [],
            },
            "notes": [],
        },
    }


class SchemaDefinitionTests(unittest.TestCase):
    def test_schema_is_json_and_policy_is_self_consistent(self):
        schema = load_schema()
        self.assertFalse(validate_schema_definition(schema))
        policy = schema["x-text2task-label-policy"]
        self.assertEqual(policy["deferred_relation_labels"], ["REFERS_TO"])
        self.assertNotIn("NONE", policy["stored_relation_labels"])
        self.assertIn("NONE", policy["candidate_relation_labels"])

    def test_all_current_candidate_records_validate_as_unannotated_records(self):
        schema = load_schema()
        total = 0
        for split, expected in (("train", 450), ("dev", 60), ("test", 90)):
            path = PROJECT_ROOT / "data" / "candidates" / f"{split}.jsonl"
            issues = validate_jsonl(path, schema)
            self.assertFalse(issues, str(issues[:3]))
            count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)
            self.assertEqual(count, expected)
            total += count
        self.assertEqual(total, 600)


class AnnotationRecordTests(unittest.TestCase):
    def test_valid_record_and_overlapping_task_artifact_spans(self):
        record = annotated_record()
        assert_valid_record(record, require_annotations=True)
        task = record["text2task_annotations"]["entities"][1]
        artifact = record["text2task_annotations"]["entities"][2]
        self.assertLess(task["start"], artifact["start"])
        self.assertEqual(task["end"], artifact["end"])

    def test_exact_character_span_is_enforced(self):
        record = annotated_record()
        record["text2task_annotations"]["entities"][2]["text"] = "Report"
        codes = {issue.code for issue in validate_record(record)}
        self.assertIn("span_text", codes)

    def test_relation_endpoint_types_are_enforced(self):
        record = annotated_record()
        record["text2task_annotations"]["relations"][0]["target_entity_id"] = "e3"
        codes = {issue.code for issue in validate_record(record)}
        self.assertIn("target_type", codes)

    def test_none_is_only_a_candidate_pair_label(self):
        record = annotated_record()
        record["text2task_annotations"]["relations"][0]["type"] = "NONE"
        codes = {issue.code for issue in validate_record(record)}
        self.assertTrue({"enum", "non_edge_label"} & codes)

        valid = annotated_record()
        self.assertFalse(validate_record(valid))
        candidate = valid["text2task_annotations"]["relation_candidates"][0]
        candidate["relation_evidence"] = {"start": 25, "end": 31, "text": "report"}
        self.assertIn("none_candidate_metadata", {issue.code for issue in validate_record(valid)})

    def test_refers_to_is_deferred_and_rejected_as_an_edge(self):
        record = annotated_record()
        record["text2task_annotations"]["relations"][0]["type"] = "REFERS_TO"
        codes = {issue.code for issue in validate_record(record)}
        self.assertTrue({"enum", "non_edge_label"} & codes)

    def test_pronoun_assignee_is_unresolved_not_invented(self):
        text = "She will send the report."
        record = {
            "id": "mailex:dev:pronoun:turn_0000",
            "source": "mailex",
            "source_split": "dev",
            "thread_id": "pronoun",
            "turn_index": 0,
            "text": text,
            "text2task_annotations": {
                "schema_version": "1.0.0",
                "annotation_status": "DRAFT",
                "annotator_id": "unit-test",
                "entities": [
                    {
                        "id": "e1",
                        "type": "TASK",
                        "start": 9,
                        "end": 24,
                        "text": "send the report",
                        "task_attributes": task_attributes(
                            operation="CREATE",
                            ambiguous=True,
                            missing_fields=["TEMPORAL"],
                            unresolved_fields=["ASSIGNEE"],
                        ),
                    },
                    {"id": "e2", "type": "ARTIFACT", "start": 18, "end": 24, "text": "report", "task_attributes": None},
                ],
                "relations": [],
                "relation_candidates": [],
                "reference_resolution": {"status": "DEFERRED_NO_REFERENCE_SPANS", "mentions": []},
                "notes": ["Pronoun resolution deferred in v1."],
            },
        }
        self.assertFalse(validate_record(record, require_annotations=True))
        self.assertFalse(any(entity["type"] == "PERSON" for entity in record["text2task_annotations"]["entities"]))

    def test_missing_information_must_be_marked(self):
        record = annotated_record()
        annotations = record["text2task_annotations"]
        annotations["relations"] = []
        attributes = annotations["entities"][1]["task_attributes"]
        attributes["missing_fields"] = []
        codes = {issue.code for issue in validate_record(record)}
        self.assertIn("assignee_marker_missing", codes)
        self.assertIn("temporal_marker_missing", codes)

    def test_resolved_cross_email_identity_requires_thread_task_id(self):
        record = annotated_record()
        attributes = record["text2task_annotations"]["entities"][1]["task_attributes"]
        attributes["identity_status"] = "RESOLVED"
        self.assertIn("resolved_identity", {issue.code for issue in validate_record(record)})
        attributes["thread_task_id"] = "thread-task:example:1"
        self.assertFalse(validate_record(record))

    def test_unknown_operation_and_status_are_explicitly_unresolved(self):
        record = annotated_record()
        attributes = record["text2task_annotations"]["entities"][1]["task_attributes"]
        attributes.update({"operation": "UNKNOWN", "status": "UNKNOWN", "ambiguous": True})
        codes = {issue.code for issue in validate_record(record)}
        self.assertIn("unknown_operation", codes)
        self.assertIn("unknown_status", codes)
        attributes["unresolved_fields"] = ["OPERATION", "STATUS"]
        self.assertFalse(validate_record(record))

    def test_require_annotations_rejects_null_annotation_set(self):
        record = annotated_record()
        record["text2task_annotations"] = None
        self.assertFalse(validate_record(record))
        self.assertIn("annotations_required", {issue.code for issue in validate_record(record, require_annotations=True)})


if __name__ == "__main__":
    unittest.main()
