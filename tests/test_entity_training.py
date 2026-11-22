import unittest
from pathlib import Path

from src.model_training.entity_extractor import (
    data_fingerprints,
    human_gold,
    load_config,
    metric_context,
    model_features,
    preflight,
)


class FakeTokenizer:
    unk_token_id = 100

    def convert_tokens_to_ids(self, token):
        if token == "[unused2]":
            return 3
        return self.unk_token_id


class EntityTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(Path("configs/entity_training.yaml"))
        cls.before = data_fingerprints(cls.config)
        cls.provisional = preflight(cls.config, mode="provisional_silver")
        cls.gold = preflight(cls.config, mode="gold_evaluation")
        cls.after = data_fingerprints(cls.config)

    def test_required_hyperparameters_are_recorded(self):
        config = load_config(Path("configs/entity_training.yaml"))
        self.assertEqual(config["model"]["name"], "distilbert/distilbert-base-uncased")
        training = config["training"]
        self.assertEqual(training["learning_rate"], 2e-5)
        self.assertEqual(training["num_train_epochs"], 3)
        self.assertEqual(training["per_device_train_batch_size"], 4)
        self.assertEqual(training["gradient_accumulation_steps"], 4)
        self.assertEqual(training["weight_decay"], 0.01)

    def test_overlap_layer_marker_does_not_change_source_labels(self):
        row = {
            "id": "row",
            "layer_index": 2,
            "input_ids": [101, 2001, 102],
            "attention_mask": [1, 1, 1],
            "label_ids": [-100, 9, -100],
        }
        features = model_features(row, FakeTokenizer(), 512)
        self.assertEqual(features["input_ids"], [101, 3, 2001, 102])
        self.assertEqual(features["labels"], [-100, -100, 9, -100])

    def test_gold_requires_completed_identified_human_review(self):
        record = {
            "annotation_provenance": {
                "quality_tier": "GOLD",
                "human_review": {
                    "review_status": "COMPLETED",
                    "quality_tier": "GOLD",
                    "reviewer": {"reviewer_id": "human:one", "completed_at": "2026-01-01T00:00:00Z"},
                },
            }
        }
        self.assertTrue(human_gold(record))
        record["annotation_provenance"]["human_review"] = None
        self.assertFalse(human_gold(record))

    def test_silver_training_is_allowed_in_provisional_mode(self):
        self.assertTrue(self.provisional["passed"], self.provisional)
        self.assertEqual(self.provisional["splits"]["validation"]["email_tiers"], {"SILVER": 60})

    def test_silver_metrics_cannot_be_misreported_as_gold(self):
        context = metric_context(self.config, "provisional_silver")
        self.assertEqual(context["metric_prefix"], "silver_provisional")
        self.assertFalse(context["is_final_research_metric"])
        self.assertEqual(context["annotation_tier"], "SILVER")

    def test_strict_gold_mode_still_blocks_without_human_review(self):
        self.assertFalse(self.gold["passed"])
        self.assertIn("validation_is_not_fully_human_reviewed_gold", self.gold["blockers"])

    def test_preflight_never_modifies_annotation_inputs(self):
        self.assertEqual(self.before, self.after)


if __name__ == "__main__":
    unittest.main()
