import json
import tempfile
import unittest
from pathlib import Path

from src.model_data.relation_classification import (
    candidate_rows_for_record,
    sample_negatives,
)
from src.model_data.token_classification import (
    DistilBertWordPieceTokenizer,
    assign_overlap_layers,
    prepare_record,
)


def annotation(entities, relations=None):
    return {"entities": entities, "relations": relations or []}


def entity(entity_id, entity_type, start, end, text):
    return {"id": entity_id, "type": entity_type, "start": start, "end": end, "text": text, "task_attributes": None}


def record(text, entities, relations=None, split="train"):
    return {
        "id": f"mailex:{split}:thread:turn_0000",
        "source": "mailex",
        "source_split": split,
        "thread_id": "thread",
        "turn_index": 0,
        "text": text,
        "text2task_annotations": annotation(entities, relations),
        "annotation_provenance": {"quality_tier": "GOLD"},
    }


class TokenDataTests(unittest.TestCase):
    def tokenizer(self, root):
        vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "please", "email", "##ing", "bob", "."]
        path = root / "vocab.txt"
        # The production guard expects a meaningful vocabulary; harmless unused
        # tokens keep this test fixture compact while exercising the same code.
        vocab.extend(f"[unused{i}]" for i in range(100))
        path.write_text("\n".join(vocab) + "\n", encoding="utf-8")
        return DistilBertWordPieceTokenizer(path)

    def test_subword_labels_and_offsets_reconstruct_span(self):
        with tempfile.TemporaryDirectory() as directory:
            tokenizer = self.tokenizer(Path(directory))
            text = "Please emailing Bob."
            item = record(text, [entity("e1", "TASK", 0, 15, "Please emailing"), entity("e2", "PERSON", 16, 19, "Bob")])
            rows, _ = prepare_record(item, tokenizer, final_split="train", max_length=16, stride=2)
            row = rows[0]
            labeled = [(token, label) for token, label in zip(row["tokens"], row["labels"]) if label not in (None, "O")]
            self.assertEqual(labeled, [("please", "B-TASK"), ("email", "I-TASK"), ("##ing", "I-TASK"), ("bob", "B-PERSON")])
            self.assertEqual(row["label_ids"][0], -100)
            self.assertEqual(row["label_ids"][-1], -100)

    def test_overlaps_are_split_into_layers_not_overwritten(self):
        spans = [
            entity("task", "TASK", 0, 12, "prepare file"),
            entity("artifact", "ARTIFACT", 8, 12, "file"),
            entity("person", "PERSON", 13, 16, "Bob"),
        ]
        layers = assign_overlap_layers(spans)
        self.assertEqual(len(layers), 2)
        ids = [item["id"] for layer in layers for item in layer]
        self.assertCountEqual(ids, ["task", "artifact", "person"])
        for layer in layers:
            for index, left in enumerate(layer):
                for right in layer[index + 1:]:
                    self.assertTrue(left["end"] <= right["start"] or right["end"] <= left["start"])

    def test_source_split_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            tokenizer = self.tokenizer(Path(directory))
            item = record("Please.", [], split="dev")
            with self.assertRaisesRegex(ValueError, "source split"):
                prepare_record(item, tokenizer, final_split="train")


class RelationDataTests(unittest.TestCase):
    def fixture(self):
        text = "Please send Bob the report tomorrow."
        entities = [
            entity("task", "TASK", 0, 26, "Please send Bob the report"),
            entity("person", "PERSON", 12, 15, "Bob"),
            entity("artifact", "ARTIFACT", 20, 26, "report"),
            entity("time", "TEMPORAL", 27, 35, "tomorrow"),
        ]
        relations = [{
            "id": "r1",
            "type": "ASSIGNED_TO",
            "source_entity_id": "task",
            "target_entity_id": "person",
            "relation_evidence": {"start": 0, "end": 15, "text": text[:15]},
            "explicit_vs_inferred": "EXPLICIT",
            "ambiguous": False,
        }]
        return record(text, entities, relations)

    def test_only_semantically_valid_pairs_are_candidates(self):
        rows, skipped, ambiguous = candidate_rows_for_record(self.fixture(), final_split="train")
        self.assertEqual((skipped, ambiguous), (0, 0))
        pairs = {(row["source_entity"]["type"], row["target_entity"]["type"]) for row in rows}
        self.assertEqual(pairs, {("TASK", "PERSON"), ("TASK", "TEMPORAL")})
        self.assertNotIn(("TASK", "ARTIFACT"), pairs)
        self.assertEqual(sum(row["label"] == "ASSIGNED_TO" for row in rows), 1)
        temporal = next(row for row in rows if row["target_entity"]["type"] == "TEMPORAL")
        self.assertEqual(temporal["candidate_relation_types"], ["DUE_ON", "SCHEDULED_ON"])

    def test_negative_sampling_is_bounded_and_deterministic(self):
        rows, _, _ = candidate_rows_for_record(self.fixture(), final_split="train")
        first = sample_negatives(rows, ratio=1.0, seed=17)
        second = sample_negatives(rows, ratio=1.0, seed=17)
        self.assertEqual([row["id"] for row in first], [row["id"] for row in second])
        self.assertEqual(sum(row["label"] == "NONE" for row in first), 1)
        self.assertEqual(sum(row["label"] != "NONE" for row in first), 1)

    def test_relation_rows_preserve_source_split_and_thread(self):
        rows, _, _ = candidate_rows_for_record(self.fixture(), final_split="train")
        self.assertTrue(rows)
        self.assertTrue(all(row["source_split"] == "train" and row["final_split"] == "train" for row in rows))
        self.assertTrue(all(row["thread_id"] == "thread" for row in rows))
        self.assertTrue(all("[E1_TASK]" in row["marked_text"] for row in rows))

    def test_invalid_positive_relation_endpoint_types_fail(self):
        item = self.fixture()
        item["text2task_annotations"]["relations"][0]["target_entity_id"] = "artifact"
        with self.assertRaisesRegex(ValueError, "invalid endpoint types"):
            candidate_rows_for_record(item, final_split="train")

    def test_predicted_entities_receive_labels_only_on_exact_span_matches(self):
        item = self.fixture()
        predicted = [
            entity("p_task", "TASK", 0, 26, "Please send Bob the report"),
            entity("p_person", "PERSON", 12, 15, "Bob"),
            entity("p_time", "TEMPORAL", 27, 35, "tomorrow"),
        ]
        rows, skipped, _ = candidate_rows_for_record(
            item,
            final_split="train",
            entity_source="predicted",
            predicted_entities=predicted,
        )
        self.assertEqual(skipped, 0)
        positive = next(row for row in rows if row["label"] == "ASSIGNED_TO")
        self.assertEqual(positive["source_entity"]["id"], "p_task")
        self.assertEqual(positive["target_entity"]["id"], "p_person")


if __name__ == "__main__":
    unittest.main()
