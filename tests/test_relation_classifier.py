import unittest
from pathlib import Path

import torch

from src.model_data.relation_classification import marked_text
from src.model_training.relation_classifier import (
    LABELS, MARKERS, RelationClassifier, allowed_mask, build_tokenizer, collate, encode_rows, prf)

ROOT = Path(__file__).resolve().parents[1]
BASE = "distilbert/distilbert-base-uncased"


class RelationClassifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = build_tokenizer(BASE)

    def test_markers_are_single_tokens(self):
        for m in MARKERS:
            self.assertEqual(len(self.tok(m, add_special_tokens=False)["input_ids"]), 1, m)

    def test_type_mask(self):
        self.assertEqual(allowed_mask("PERSON"), [True, True, False, False])
        self.assertEqual(allowed_mask("TEMPORAL"), [True, False, True, True])

    def test_prf_handles_none_and_support(self):
        gold = ["NONE", "ASSIGNED_TO", "DUE_ON", "NONE"]
        pred = ["ASSIGNED_TO", "ASSIGNED_TO", "NONE", "NONE"]
        m = prf(gold, pred)
        self.assertEqual(m["ASSIGNED_TO"]["tp"], 1)
        self.assertEqual(m["ASSIGNED_TO"]["fp"], 1)
        self.assertEqual(m["DUE_ON"]["support"], 1)
        self.assertEqual(m["NONE"]["false_positive_rate"], 0.5)

    def test_forward_masks_illegal_labels_and_resizes_embeddings(self):
        text = "Riya, please submit the report by Friday."
        task = {"type": "TASK", "start": 6 + 8, "end": 6 + 8 + 17, "text": "submit the report"}
        text = "Riya, please submit the report by Friday."
        s = text.index("submit the report")
        task = {"type": "TASK", "start": s, "end": s + 17, "text": "submit the report"}
        tgt = {"type": "PERSON", "start": 0, "end": 4, "text": "Riya"}
        row = {"marked_text": marked_text(text, task, tgt), "target_entity": tgt, "label": "ASSIGNED_TO"}
        items = encode_rows([row], self.tok)
        self.assertTrue(items[0]["representable"])
        model = RelationClassifier(BASE, self.tok, "markers", load_base=False)
        self.assertEqual(model.encoder.get_input_embeddings().weight.shape[0], len(self.tok))
        ids, att, mask, _ = collate(items, self.tok.pad_token_id, "cpu")
        logits = model(ids, att, mask)
        self.assertEqual(logits.shape, (1, len(LABELS)))
        self.assertTrue((logits[0, 2:] < -1e3).all())  # DUE_ON / SCHEDULED_ON illegal for PERSON


if __name__ == "__main__":
    unittest.main()
