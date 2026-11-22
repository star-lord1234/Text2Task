import json
import tempfile
import unittest
from pathlib import Path

from scripts.convert_mailex import (
    REQUIRED_RECORD_KEYS,
    align_raw_blocks,
    convert,
    convert_split,
    parse_recipients,
    reconstruct_text,
    record_id,
    token_surface,
    validate_record,
)


class ReconstructionTests(unittest.TestCase):
    def test_offsets_reconstruct_every_token(self):
        tokens = ["I", "ca", "n't", "go", ",", "Bob", "."]
        text, offsets = reconstruct_text(tokens)
        self.assertEqual(text, "I can't go, Bob.")
        self.assertEqual(len(tokens), len(offsets))
        for token, (start, end) in zip(tokens, offsets):
            self.assertEqual(text[start:end], token)

    def test_nested_empty_token_is_preserved_as_zero_width_span(self):
        tokens = [[""]]
        text, offsets = reconstruct_text(tokens)
        self.assertEqual(text, "")
        self.assertEqual(offsets, [[0, 0]])
        self.assertEqual(text[offsets[0][0] : offsets[0][1]], token_surface(tokens[0]))

    def test_trailing_nested_empty_token_keeps_original_index(self):
        tokens = ["hello", [""]]
        text, offsets = reconstruct_text(tokens)
        self.assertEqual(text, "hello")
        self.assertEqual(offsets, [[0, 5], [5, 5]])


class IdentifierTests(unittest.TestCase):
    def test_identifier_is_deterministic_and_split_qualified(self):
        first = record_id("train", "bass-e_inbox114", 2)
        self.assertEqual(first, "mailex:train:bass-e_inbox114:turn_0002")
        self.assertEqual(first, record_id("train", "bass-e_inbox114", 2))
        self.assertNotEqual(first, record_id("dev", "bass-e_inbox114", 2))
        self.assertNotEqual(first, record_id("train", "bass-e_inbox114", 3))


class RawMetadataTests(unittest.TestCase):
    def test_alignment_handles_reverse_raw_order(self):
        turns = ["Please send the report.", "The report is attached."]
        blocks = [
            {"raw_block_index": 0, "headers": {"FROM": "b@example.com"}, "body": "The report is attached."},
            {"raw_block_index": 1, "headers": {"FROM": "a@example.com"}, "body": "Please send the report."},
        ]
        aligned, rejected = align_raw_blocks(turns, blocks, threshold=0.55)
        self.assertFalse(rejected)
        self.assertEqual(aligned[0]["raw_block_index"], 1)
        self.assertEqual(aligned[1]["raw_block_index"], 0)

    def test_recipient_parsing_preserves_comma_display_names(self):
        self.assertEqual(parse_recipients("Bass, Eric; Doe, Jane"), ["Bass, Eric", "Doe, Jane"])
        self.assertEqual(parse_recipients("a@example.com, b@example.com"), ["a@example.com", "b@example.com"])
        self.assertEqual(parse_recipients(None), [])


class SplitConversionTests(unittest.TestCase):
    @staticmethod
    def _mail_event(token_count):
        return {
            "O": {
                "labels": [["O"] * token_count],
                "triggers": [""],
                "extras": [""],
            }
        }

    def test_split_preservation_and_full_data_exclusion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = root / "mailex"
            output = root / "unified"
            report = root / "conversion_report.md"
            for split in ("train", "dev", "test", "full_data"):
                (dataset / split).mkdir(parents=True)

            expected_by_split = {}
            for split in ("train", "dev", "test"):
                expected_by_split[split] = []
                for number in range(4):
                    filename = f"{split}_thread_{number}.json"
                    tokens = ["Hello", ",", split, str(number), "."]
                    payload = {
                        "sentences": [tokens],
                        "events": {"turn_0": self._mail_event(len(tokens))},
                    }
                    (dataset / split / filename).write_text(json.dumps(payload), encoding="utf-8")
                    expected_by_split[split].append(filename)

            # This record must never appear in the output.
            rogue = {
                "sentences": [["ROGUE"]],
                "events": {"turn_0": self._mail_event(1)},
            }
            (dataset / "full_data" / "rogue.json").write_text(json.dumps(rogue), encoding="utf-8")

            result = convert(dataset, output, report)
            self.assertEqual(result["total_records"], 12)
            self.assertTrue(report.is_file())

            all_ids = set()
            for split in ("train", "dev", "test"):
                lines = (output / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(lines), 4)
                records = [json.loads(line) for line in lines]
                self.assertEqual({record["source_split"] for record in records}, {split})
                self.assertEqual({record["source_filename"] for record in records}, set(expected_by_split[split]))
                self.assertNotIn("rogue.json", {record["source_filename"] for record in records})
                for record in records:
                    self.assertEqual(set(record), REQUIRED_RECORD_KEYS)
                    self.assertFalse(validate_record(record))
                    self.assertIsNone(record["sender"])
                    self.assertEqual(record["recipients"], [])
                    self.assertIsNone(record["timestamp"])
                    self.assertEqual(record["turn_index"], 0)
                    self.assertEqual(record["original_events"], self._mail_event(5))
                    self.assertNotIn(record["id"], all_ids)
                    all_ids.add(record["id"])

    def test_turn_order_context_tokens_and_events_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "mailex"
            (dataset / "train").mkdir(parents=True)
            first_tokens = ["Please", "send", "it", "."]
            second_tokens = ["Sent", "."]
            first_events = self._mail_event(len(first_tokens))
            second_events = self._mail_event(len(second_tokens))
            payload = {
                "sentences": [first_tokens, second_tokens],
                "events": {"turn_0": first_events, "turn_1": second_events},
            }
            (dataset / "train" / "thread_a.json").write_text(json.dumps(payload), encoding="utf-8")

            records, stats = convert_split("train", dataset, raw_lookup={}, raw_threshold=0.55)
            self.assertEqual(stats["turns"], 2)
            self.assertEqual([record["turn_index"] for record in records], [0, 1])
            self.assertEqual([record["tokens"] for record in records], [first_tokens, second_tokens])
            self.assertEqual([record["original_events"] for record in records], [first_events, second_events])
            self.assertIsNone(records[0]["thread_context"]["previous_record_id"])
            self.assertEqual(records[0]["thread_context"]["next_record_id"], records[1]["id"])
            self.assertEqual(records[1]["thread_context"]["previous_record_id"], records[0]["id"])
            self.assertIsNone(records[1]["thread_context"]["next_record_id"])


if __name__ == "__main__":
    unittest.main()
