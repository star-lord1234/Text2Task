import unittest

from scripts.convert_mailex import reconstruct_text
from src.preprocessing.clean_emails import clean_record, validate_clean_alignment


def make_record(tokens, labels=None, triggers=None, record_id="mailex:train:test:turn_0000"):
    text, offsets = reconstruct_text(tokens)
    labels = labels if labels is not None else ["O"] * len(tokens)
    triggers = triggers if triggers is not None else [""]
    return {
        "id": record_id,
        "source": "mailex",
        "source_split": "train",
        "source_filename": "test.json",
        "thread_id": "test",
        "turn_index": 0,
        "text": text,
        "tokens": tokens,
        "token_offsets": offsets,
        "sender": None,
        "recipients": [],
        "timestamp": None,
        "subject": None,
        "thread_context": {
            "turn_count": 1,
            "previous_record_id": None,
            "next_record_id": None,
            "raw_thread_filename": None,
            "raw_block_index": None,
            "raw_alignment_score": None,
        },
        "original_events": {
            "Request_Action": {
                "labels": [labels],
                "triggers": triggers,
                "extras": [""],
            }
        },
        "text2task_annotations": None,
    }


class ConservativeCleaningTests(unittest.TestCase):
    def test_instruction_negation_name_and_temporal_expression_remain_intact(self):
        tokens = ["Alice", ",", "do", "not", "send", "the", "report", "before", "Friday", "at", "5", "PM", "."]
        labels = ["O"] * len(tokens)
        for index in range(2, 12):
            labels[index] = "Request_Action:B-Action Description" if index == 2 else "Request_Action:I-Action Description"
        record = make_record(tokens, labels=labels, triggers=["{'words': 'do not send', 'indices': '2 3 4'}"])
        cleaned = clean_record(record)
        self.assertEqual(cleaned["text"], cleaned["text_raw"])
        self.assertIn("Alice", cleaned["text"])
        self.assertIn("do not send", cleaned["text"])
        self.assertIn("before Friday at 5 PM", cleaned["text"])
        self.assertFalse(cleaned["cleaning"]["removed_token_indices"])
        self.assertFalse(validate_clean_alignment(cleaned))

    def test_unannotated_legal_disclaimer_is_removed_with_exact_mapping(self):
        tokens = [
            "Please", "send", "the", "report", "by", "Friday", ".",
            "This", "e-mail", "is", "the", "property", "of", "Enron", ".",
            "This", "is", "confidential", "and", "privileged", "for", "the", "intended", "recipient", ".",
            "Delete", "all", "copies", ".",
        ]
        record = make_record(tokens)
        cleaned = clean_record(record)
        self.assertEqual(cleaned["text"], "Please send the report by Friday.")
        self.assertIn("Friday", cleaned["text"])
        removed = cleaned["cleaning"]["removed_token_indices"]
        self.assertEqual(removed, list(range(7, len(tokens))))
        self.assertTrue(all(cleaned["token_offsets"][index] is None for index in removed))
        operations = [op for op in cleaned["cleaning"]["operations"] if op["type"] == "legal_disclaimer"]
        self.assertEqual(operations[0]["action"], "removed")
        self.assertIn("This e-mail is the property of Enron", operations[0]["original_text"])
        self.assertFalse(validate_clean_alignment(cleaned))

    def test_disclaimer_overlapping_annotation_is_preserved_and_flagged(self):
        tokens = [
            "Please", "send", "it", ".",
            "This", "e-mail", "is", "the", "property", "of", "Enron", ".",
            "This", "is", "confidential", "and", "privileged", "for", "the", "intended", "recipient", ".",
            "Delete", "all", "copies", ".",
        ]
        labels = ["O"] * len(tokens)
        labels[4] = "Request_Action:B-Action Description"
        record = make_record(tokens, labels=labels)
        cleaned = clean_record(record)
        self.assertEqual(cleaned["text"], cleaned["text_raw"])
        self.assertIn("legal_disclaimer_overlaps_annotation", cleaned["cleaning"]["review_flags"])
        operation = next(op for op in cleaned["cleaning"]["operations"] if op["type"] == "legal_disclaimer")
        self.assertEqual(operation["action"], "preserved_for_review")
        self.assertIn(4, operation["protected_overlap"])

    def test_trailing_quote_is_removed_but_preserved_as_context(self):
        tokens = [
            "Please", "review", "this", "today", ".",
            "----- Original Message -----", "From", ":", "Bob", "Sent", ":", "Yesterday", "Old", "context", ".",
        ]
        record = make_record(tokens)
        cleaned = clean_record(record)
        self.assertEqual(cleaned["text"], "Please review this today.")
        self.assertEqual(len(cleaned["quoted_context"]), 1)
        self.assertTrue(cleaned["quoted_context"][0]["removed_from_text"])
        self.assertIn("Old context", cleaned["quoted_context"][0]["text"])

    def test_ambiguous_signature_is_preserved_for_review(self):
        tokens = ["Please", "send", "the", "file", "tomorrow", ".", "Thanks", ",", "Bob"]
        cleaned = clean_record(make_record(tokens))
        self.assertIn("Please send the file tomorrow", cleaned["text"])
        self.assertIn("Thanks, Bob", cleaned["text"])
        self.assertIn("review_email_signature", cleaned["cleaning"]["review_flags"])
        signature = next(op for op in cleaned["cleaning"]["operations"] if op["type"] == "email_signature")
        self.assertEqual(signature["action"], "preserved_for_review")

    def test_signature_candidate_with_temporal_evidence_is_never_auto_removed(self):
        tokens = [
            "Please", "send", "the", "important", "file", "to", "Alice", "and", "Bob", "after", "the", "review", ".",
            "The", "attached", "version", "contains", "all", "requested", "changes", ".",
            "Thank", "you", "for", "meeting", "next", "week", ".",
            "Susan", "Scott", "713-775-6472",
        ]
        cleaned = clean_record(make_record(tokens))
        self.assertIn("meeting next week", cleaned["text"])
        signature = next(op for op in cleaned["cleaning"]["operations"] if op["type"] == "email_signature")
        self.assertEqual(signature["action"], "preserved_for_review")

    def test_known_encoding_artifact_is_modified_without_reordering(self):
        tokens = ["Alice", "â€™", "will", "send", "it", "tomorrow", "."]
        cleaned = clean_record(make_record(tokens))
        self.assertEqual(cleaned["text"], "Alice ’ will send it tomorrow.")
        self.assertFalse(validate_clean_alignment(cleaned))
        operation = next(op for op in cleaned["cleaning"]["operations"] if op["type"] == "encoding_artifact")
        self.assertEqual(operation["action"], "modified")

    def test_unreliable_source_alignment_falls_back_to_raw(self):
        record = make_record(["Send", "today", "."])
        record["token_offsets"][1] = [999, 1000]
        cleaned = clean_record(record)
        self.assertEqual(cleaned["cleaning"]["alignment_status"], "fallback_raw")
        self.assertEqual(cleaned["cleaning"]["training_text_source"], "text_raw")
        self.assertEqual(cleaned["text"], cleaned["text_raw"])


if __name__ == "__main__":
    unittest.main()
