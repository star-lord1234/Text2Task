import json
import unittest
from pathlib import Path

from src.model_training.span_metrics import decode_spans, evaluate


class DecodeTests(unittest.TestCase):
    def test_basic_and_adjacent_spans(self):
        labels = ["B-TASK", "I-TASK", "O", "B-PERSON", "B-PERSON", "I-TEMPORAL"]
        self.assertEqual(
            [("TASK", 0, 2), ("PERSON", 3, 4), ("PERSON", 4, 5), ("TEMPORAL", 5, 6)],
            decode_spans(labels),
        )

    def test_orphan_i_starts_span_like_seqeval(self):
        self.assertEqual([("TASK", 1, 3)], decode_spans(["O", "I-TASK", "I-TASK"]))

    def test_type_change_without_b_splits(self):
        self.assertEqual([("TASK", 0, 1), ("PERSON", 1, 2)], decode_spans(["B-TASK", "I-PERSON"]))


class EvaluateTests(unittest.TestCase):
    TYPES = ["TASK", "PERSON", "TEMPORAL"]

    def test_perfect_prediction(self):
        ref = [["B-TASK", "I-TASK", "O", "B-PERSON"]]
        result = evaluate(ref, ref, self.TYPES)
        for name in ("strict", "lenient", "overlap_any", "token"):
            self.assertEqual(1.0, result["overall"][name]["f1"])

    def test_boundary_error_scores_zero_strict_but_credit_lenient(self):
        ref = [["B-TASK", "I-TASK", "I-TASK", "I-TASK", "O"]]
        pred = [["B-TASK", "I-TASK", "I-TASK", "O", "O"]]  # IoU = 3/4
        result = evaluate(pred, ref, self.TYPES)
        self.assertEqual(0.0, result["overall"]["strict"]["f1"])
        self.assertEqual(1.0, result["overall"]["lenient"]["f1"])
        self.assertAlmostEqual(6 / 7, result["overall"]["token"]["f1"])

    def test_short_prediction_inside_long_span_fails_lenient_but_passes_overlap_any(self):
        ref = [["B-TASK"] + ["I-TASK"] * 9]
        pred = [["B-TASK"] + ["O"] * 9]  # IoU = 1/10
        result = evaluate(pred, ref, self.TYPES)
        self.assertEqual(0.0, result["overall"]["lenient"]["f1"])
        self.assertEqual(1.0, result["overall"]["overlap_any"]["f1"])

    def test_wrong_type_never_matches(self):
        ref = [["B-TASK", "I-TASK"]]
        pred = [["B-PERSON", "I-PERSON"]]
        result = evaluate(pred, ref, self.TYPES)
        for name in ("strict", "lenient", "overlap_any", "token"):
            self.assertEqual(0.0, result["overall"][name]["f1"])

    def test_matching_is_one_to_one(self):
        ref = [["B-TASK", "I-TASK", "I-TASK", "I-TASK"]]
        pred = [["B-TASK", "I-TASK", "B-TASK", "I-TASK"]]  # two halves; each IoU 0.5
        result = evaluate(pred, ref, self.TYPES)
        self.assertEqual(1, result["overall"]["lenient"]["matched"])
        self.assertEqual(1, result["overall"]["overlap_any"]["matched"])

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            evaluate([["O"]], [["O", "O"]], self.TYPES)

    def test_strict_matches_seqeval_on_real_predictions(self):
        path = Path("results/entity_extraction/entity_v2_three_class/epoch3_sqrt_weighted/validation_predictions.jsonl")
        if not path.exists():
            self.skipTest("v2 prediction file not present")
        try:
            from seqeval.metrics import f1_score, precision_score, recall_score
        except ImportError:
            self.skipTest("seqeval not installed")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        pred = [r["predictions"] for r in rows]
        ref = [r["references"] for r in rows]
        overall = evaluate(pred, ref, self.TYPES)["overall"]["strict"]
        self.assertAlmostEqual(f1_score(ref, pred, zero_division=0), overall["f1"], places=9)
        self.assertAlmostEqual(precision_score(ref, pred, zero_division=0), overall["precision"], places=9)
        self.assertAlmostEqual(recall_score(ref, pred, zero_division=0), overall["recall"], places=9)


if __name__ == "__main__":
    unittest.main()
