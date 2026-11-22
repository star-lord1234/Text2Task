import unittest
from pathlib import Path

from src.model_training.entity_inference import EntityPredictor, decode

ROOT = Path(__file__).resolve().parents[1]
CKPT = ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted"


class DecodeTests(unittest.TestCase):
    def test_bio_decoding_merges_continuations_and_keeps_offsets(self):
        text = "Riya send the report"
        votes = {(0, 4): ("B-PERSON", 0.9), (5, 9): ("B-TASK", 0.8), (10, 13): ("I-TASK", 0.7), (14, 20): ("I-TASK", 0.6)}
        ents = decode(text, votes)
        self.assertEqual([(e["type"], e["text"], e["start"], e["end"]) for e in ents], [("PERSON", "Riya", 0, 4), ("TASK", "send the report", 5, 20)])
        self.assertAlmostEqual(ents[1]["confidence"], (0.8 + 0.7 + 0.6) / 3)

    def test_outside_labels_break_spans_and_type_change_starts_new_span(self):
        ents = decode("a b c", {(0, 1): ("B-TASK", 0.5), (2, 3): ("O", 0.9), (4, 5): ("I-TASK", 0.5)})
        self.assertEqual([(e["type"], e["text"]) for e in ents], [("TASK", "a"), ("TASK", "c")])
        self.assertEqual(decode("", {}), [])


@unittest.skipUnless(CKPT.is_dir(), "entity checkpoint not present")
class PredictorTests(unittest.TestCase):
    def test_real_checkpoint_returns_valid_spans(self):
        p = EntityPredictor(CKPT)
        text = "Bianca, please prepare the report by Friday."
        ents = p.predict(text)
        self.assertTrue(all(text[e["start"]:e["end"]] == e["text"] for e in ents))
        self.assertTrue(all(e["type"] in {"TASK", "PERSON", "TEMPORAL"} for e in ents))


if __name__ == "__main__":
    unittest.main()
