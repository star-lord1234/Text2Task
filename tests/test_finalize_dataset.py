import json
import tempfile
import unittest
from pathlib import Path

from src.annotation.finalize_dataset import FinalizerConfig, assemble_dataset
from src.annotation.review_workflow import blank_annotation


def source_record(split, record_id, text, thread_id):
    return {
        "id": record_id,
        "source": "mailex",
        "source_split": split,
        "source_filename": f"{thread_id}.json",
        "thread_id": thread_id,
        "turn_index": 0,
        "text": text,
        "original_events": {},
        "text2task_annotations": None,
    }


def annotated(record, *, human=False, tier="GOLD"):
    output = dict(record)
    output["text2task_annotations"] = blank_annotation("human:test" if human else "fake:model")
    if human:
        output["human_review"] = {
            "review_status": "COMPLETED",
            "quality_tier": tier,
            "reviewer": {
                "reviewer_id": "human:test",
                "completed_at": "2026-01-01T00:00:00Z",
            },
        }
    else:
        output["llm_annotation_metadata"] = {"provider": "fake", "model": "test"}
    return output


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


class FinalDatasetTests(unittest.TestCase):
    def make_config(self, root):
        return FinalizerConfig(
            cleaned_dir=root / "cleaned",
            gold_dir=root / "gold",
            silver_paths=[root / "silver" / "train.jsonl", root / "silver" / "dev.jsonl"],
            rejected_dir=root / "rejected",
            output_dir=root / "final",
            report_path=root / "report.md",
            integrity_path=root / "integrity.json",
            small_test_threshold=1,
        )

    def seed_cleaned(self, root, texts=None):
        texts = texts or {
            "train": "Please prepare the alpha report.",
            "dev": "Please prepare the beta report.",
            "test": "Please prepare the gamma report.",
        }
        records = {}
        for split in ("train", "dev", "test"):
            record = source_record(split, f"mailex:{split}:one:turn_0000", texts[split], f"{split}-thread")
            write_jsonl(root / "cleaned" / f"{split}.jsonl", [record])
            write_jsonl(root / "gold" / f"{split}.jsonl", [])
            write_jsonl(root / "rejected" / f"{split}.jsonl", [])
            records[split] = record
        write_jsonl(root / "silver" / "train.jsonl", [])
        write_jsonl(root / "silver" / "dev.jsonl", [])
        return records

    def test_ready_assembly_preserves_splits_and_annotation_tiers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            records = self.seed_cleaned(root)
            write_jsonl(root / "silver" / "train.jsonl", [annotated(records["train"])])
            write_jsonl(root / "gold" / "dev.jsonl", [annotated(records["dev"], human=True)])
            write_jsonl(root / "gold" / "test.jsonl", [annotated(records["test"], human=True)])
            integrity = assemble_dataset(self.make_config(root))
            self.assertTrue(integrity["ready_for_ml"], integrity["blocking_issues"])
            self.assertEqual(integrity["split_statistics"]["train"]["silver_records"], 1)
            self.assertEqual(integrity["split_statistics"]["validation"]["gold_records"], 1)
            self.assertEqual(integrity["split_statistics"]["test"]["gold_records"], 1)
            validation = json.loads((root / "final" / "validation.jsonl").read_text())
            self.assertEqual(validation["source_split"], "dev")
            self.assertIn("original_events", validation)
            self.assertEqual(validation["annotation_provenance"]["quality_tier"], "GOLD")

    def test_raw_silver_is_excluded_from_evaluation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            records = self.seed_cleaned(root)
            write_jsonl(root / "silver" / "train.jsonl", [annotated(records["train"])])
            write_jsonl(root / "silver" / "dev.jsonl", [annotated(records["dev"])])
            integrity = assemble_dataset(self.make_config(root))
            self.assertEqual(integrity["split_statistics"]["validation"]["emails"], 0)
            reasons = [reason for item in integrity["quarantined_annotations"] for reason in item["reasons"]]
            self.assertIn("evaluation_requires_human_verified_gold", reasons)
            self.assertIn("validation_has_no_human_verified_examples", integrity["blocking_issues"])

    def test_explicit_silver_evaluation_override_keeps_original_splits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            records = self.seed_cleaned(root)
            write_jsonl(root / "silver" / "train.jsonl", [annotated(records["train"])])
            write_jsonl(root / "silver" / "dev.jsonl", [annotated(records["dev"])])
            silver_test = root / "silver" / "test.jsonl"
            write_jsonl(silver_test, [annotated(records["test"])])
            config = self.make_config(root)
            config.silver_paths.append(silver_test)
            config.allow_silver_evaluation = True
            integrity = assemble_dataset(config)
            self.assertTrue(integrity["ready_for_ml"], integrity["blocking_issues"])
            self.assertEqual(integrity["status"], "READY_SILVER_ONLY")
            self.assertEqual(integrity["split_statistics"]["validation"]["silver_records"], 1)
            self.assertEqual(integrity["split_statistics"]["test"]["silver_records"], 1)
            self.assertEqual(integrity["human_verified_evaluation_counts"], {"validation": 0, "test": 0})

    def test_cross_split_duplicate_quarantines_lower_priority_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            records = self.seed_cleaned(
                root,
                {
                    "train": "This exact message appears in heldout data.",
                    "dev": "A unique validation message.",
                    "test": "This exact message appears in heldout data.",
                },
            )
            write_jsonl(root / "silver" / "train.jsonl", [annotated(records["train"])])
            write_jsonl(root / "gold" / "dev.jsonl", [annotated(records["dev"], human=True)])
            write_jsonl(root / "gold" / "test.jsonl", [annotated(records["test"], human=True)])
            integrity = assemble_dataset(self.make_config(root))
            self.assertEqual(integrity["split_statistics"]["train"]["emails"], 0)
            self.assertEqual(integrity["split_statistics"]["test"]["emails"], 1)
            reasons = [reason for item in integrity["quarantined_annotations"] for reason in item["reasons"]]
            self.assertIn("cross_split_near_or_exact_duplicate_thread", reasons)

    def test_invalid_span_is_quarantined(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            records = self.seed_cleaned(root)
            bad = annotated(records["train"])
            bad["text2task_annotations"]["entities"] = [
                {
                    "id": "e1",
                    "type": "PERSON",
                    "start": 0,
                    "end": 6,
                    "text": "WRONG!",
                    "task_attributes": None,
                }
            ]
            write_jsonl(root / "silver" / "train.jsonl", [bad])
            integrity = assemble_dataset(self.make_config(root))
            self.assertEqual(integrity["split_statistics"]["train"]["emails"], 0)
            reasons = [reason for item in integrity["quarantined_annotations"] for reason in item["reasons"]]
            self.assertTrue(any(reason.startswith("span_text:") for reason in reasons))


if __name__ == "__main__":
    unittest.main()
