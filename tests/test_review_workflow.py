import json
import tempfile
import unittest
from pathlib import Path

from src.annotation.review_workflow import (
    add_entity,
    add_relation,
    blank_annotation,
    build_quality_outputs,
    finalize_reviews,
    make_review_document,
    mark_review,
    prepare_review_documents,
    render_review,
    save_review,
    set_task_attribute,
    validate_review_document,
)


def source_record(split="dev"):
    return {
        "id": f"mailex:{split}:thread:turn_0000",
        "source": "mailex",
        "source_split": split,
        "thread_id": "thread",
        "turn_index": 0,
        "text": "Alice, please send report by Friday.",
        "text2task_annotations": None,
    }


def predicted_record(split="dev"):
    record = source_record(split)
    annotation = blank_annotation("fake:model")
    annotation["entities"] = [
        {
            "id": "e1",
            "type": "PERSON",
            "start": 0,
            "end": 5,
            "text": "Alice",
            "task_attributes": None,
        }
    ]
    record["text2task_annotations"] = annotation
    record["llm_annotation_metadata"] = {"provider": "fake", "model": "test"}
    return record


class ReviewPreparationTests(unittest.TestCase):
    def test_dev_defaults_to_independent_and_preserves_hidden_prediction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "dev.jsonl"
            prediction_path = root / "prediction.jsonl"
            source_path.write_text(json.dumps(source_record()) + "\n", encoding="utf-8")
            prediction_path.write_text(json.dumps(predicted_record()) + "\n", encoding="utf-8")
            counts = prepare_review_documents([source_path], [prediction_path], [], root / "reviews")
            self.assertEqual(counts["created"], 1)
            path = next((root / "reviews").rglob("*.review.json"))
            document = json.loads(path.read_text())
            self.assertEqual(document["review_mode"], "INDEPENDENT")
            self.assertEqual(document["working_annotation"]["entities"], [])
            self.assertEqual(document["original_prediction"]["entities"][0]["text"], "Alice")
            self.assertTrue(document["prompt_feedback_eligible"])
            rendered = render_review(document)
            self.assertIn("hidden during independent review", rendered)
            self.assertNotIn("e1 PERSON", rendered)

    def test_test_records_are_never_prompt_feedback_eligible(self):
        document = make_review_document(source_record("test"), predicted_record("test"), mode="INDEPENDENT")
        self.assertFalse(document["prompt_feedback_eligible"])
        document["prompt_feedback_eligible"] = True
        codes = {issue["code"] for issue in validate_review_document(document)["issues"]}
        self.assertIn("test_feedback_leak", codes)

    def test_immutable_prediction_tampering_is_detected(self):
        document = make_review_document(source_record(), predicted_record(), mode="VERIFY")
        document["original_prediction"]["entities"][0]["text"] = "Mallory"
        codes = {issue["code"] for issue in validate_review_document(document)["issues"]}
        self.assertIn("original_prediction_modified", codes)

    def test_prepare_refuses_to_overwrite_started_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "dev.jsonl"
            source_path.write_text(json.dumps(source_record()) + "\n", encoding="utf-8")
            prepare_review_documents([source_path], [], [], root / "reviews")
            path = next((root / "reviews").rglob("*.review.json"))
            document = json.loads(path.read_text())
            document["reviewer"]["started_at"] = "2026-01-01T00:00:00Z"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
                prepare_review_documents([source_path], [], [], root / "reviews", overwrite=True)


class ReviewCorrectionTests(unittest.TestCase):
    def make_valid_review(self):
        document = make_review_document(source_record(), predicted_record(), mode="VERIFY")
        add_entity(document, "reviewer-a", "e2", "TASK", 14, 25)
        add_entity(document, "reviewer-a", "e3", "TEMPORAL", 29, 35)
        for key, value in {
            "operation": "CREATE",
            "status": "PENDING",
            "ambiguous": False,
            "missing_fields": [],
            "unresolved_fields": [],
        }.items():
            set_task_attribute(document, "reviewer-a", "e2", key, value)
        add_relation(document, "reviewer-a", "r1", "ASSIGNED_TO", "e2", "e1", 0, 25)
        add_relation(document, "reviewer-a", "r2", "DUE_ON", "e2", "e3", 14, 35)
        return document

    def test_corrections_validate_and_original_prediction_is_immutable(self):
        document = self.make_valid_review()
        validation = validate_review_document(document)
        self.assertTrue(validation["valid"], validation["issues"])
        self.assertEqual(document["original_prediction"]["entities"], predicted_record()["text2task_annotations"]["entities"])
        self.assertGreater(len(document["correction_events"]), 1)

    def test_invalid_offsets_and_dependency_are_highlighted(self):
        document = self.make_valid_review()
        document["working_annotation"]["entities"][0]["text"] = "Wrong"
        document["working_annotation"]["relations"].append({
            "id": "r3",
            "type": "DEPENDS_ON",
            "source_entity_id": "e2",
            "target_entity_id": "e2",
            "relation_evidence": {"start": 7, "end": 13, "text": "please"},
            "explicit_vs_inferred": "INFERRED",
            "ambiguous": True,
        })
        validation = validate_review_document(document)
        codes = {issue["code"] for issue in validation["issues"]}
        self.assertIn("span_text", codes)
        self.assertIn("dependency_semantic_review_required", codes)
        self.assertIn("unsupported_relation_evidence", codes)
        self.assertIn("INVALID OFFSET", render_review(document, reveal_prediction=True))

    def test_gold_requires_real_human_confirmation(self):
        document = self.make_valid_review()
        with self.assertRaisesRegex(ValueError, "Human confirmation"):
            mark_review(document, "reviewer-a", "GOLD", confirm_human=False)
        mark_review(document, "reviewer-a", "GOLD", confirm_human=True)
        self.assertEqual(document["quality_tier"], "GOLD")
        self.assertEqual(document["working_annotation"]["annotation_status"], "REVIEWED")

    def test_finalize_preserves_original_and_builds_statistics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_root = root / "reviews"
            document = self.make_valid_review()
            mark_review(document, "reviewer-a", "GOLD", confirm_human=True)
            review_path = review_root / "dev" / "record.review.json"
            save_review(review_path, document)
            counts = finalize_reviews(review_root, root / "gold", root / "silver", root / "rejected")
            self.assertEqual(counts["exported_gold"], 1)
            exported = json.loads((root / "gold" / "dev.jsonl").read_text())
            self.assertEqual(exported["llm_prediction_original"]["entities"][0]["text"], "Alice")
            self.assertEqual(exported["human_review"]["quality_tier"], "GOLD")
            stats = build_quality_outputs(review_root, root / "quality.md", root / "stats.csv")
            self.assertEqual(stats["completed"], 1)
            self.assertIn("entity_added", (root / "stats.csv").read_text())
            self.assertIn("Human-completed reviews: 1", (root / "quality.md").read_text())


if __name__ == "__main__":
    unittest.main()
