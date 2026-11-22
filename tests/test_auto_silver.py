import unittest

from src.annotation.auto_silver import annotate_record, decode_spans
from src.annotation.validators import validate_record


def record_from_tokens(tokens, labels, event_type="Request_Action", trigger=""):
    text = " ".join(tokens)
    offsets = []
    cursor = 0
    for token in tokens:
        offsets.append([cursor, cursor + len(token)])
        cursor += len(token) + 1
    return {
        "id": "mailex:train:synthetic:turn_0000",
        "source": "mailex",
        "source_split": "train",
        "thread_id": "synthetic",
        "turn_index": 0,
        "text": text,
        "tokens": tokens,
        "token_offsets": offsets,
        "original_events": {
            event_type: {
                "labels": [labels],
                "triggers": [trigger],
                "extras": [""],
            }
        },
        "text2task_annotations": None,
        "candidate_selection": {"selection_signals": {"prerequisite_matches": []}},
    }


class AutoSilverTests(unittest.TestCase):
    def test_bio_decoder_recovers_role_transition_i(self):
        spans = decode_spans([
            "Request_Action:B-Action Description",
            "Request_Action:I-Action Description",
            "Request_Action:I-Action Members",
        ])
        self.assertEqual([(s.role, s.token_start, s.token_end) for s in spans], [
            ("Action Description", 0, 2),
            ("Action Members", 2, 3),
        ])

    def test_action_members_task_and_deadline_map_to_valid_graph(self):
        record = record_from_tokens(
            ["Alice", "send", "report", "by", "Friday"],
            [
                "Request_Action:B-Action Members",
                "Request_Action:B-Action Description",
                "Request_Action:I-Action Description",
                "Request_Action:B-Action Date",
                "Request_Action:I-Action Date",
            ],
        )
        output = annotate_record(record)
        self.assertEqual(validate_record(output, require_annotations=True), [])
        annotation = output["text2task_annotations"]
        self.assertEqual({entity["type"] for entity in annotation["entities"]}, {"PERSON", "TASK", "TEMPORAL"})
        self.assertEqual({relation["type"] for relation in annotation["relations"]}, {"ASSIGNED_TO", "DUE_ON"})

    def test_pronoun_owner_remains_unresolved(self):
        record = record_from_tokens(
            ["You", "send", "report"],
            [
                "Request_Action:B-Action Members",
                "Request_Action:B-Action Description",
                "Request_Action:I-Action Description",
            ],
        )
        output = annotate_record(record)
        annotation = output["text2task_annotations"]
        task = next(entity for entity in annotation["entities"] if entity["type"] == "TASK")
        self.assertIn("ASSIGNEE", task["task_attributes"]["unresolved_fields"])
        self.assertFalse(any(entity["type"] in {"PERSON", "GROUP"} for entity in annotation["entities"]))
        self.assertEqual(validate_record(output, require_annotations=True), [])

    def test_high_confidence_dependency_adds_reviewable_event_edge(self):
        record = record_from_tokens(
            ["Prepare", "report", "dependent", "on", "approval", "."],
            [
                "Request_Action:B-Action Description",
                "Request_Action:I-Action Description",
                "O", "O", "O", "O",
            ],
        )
        start = record["text"].index("dependent on")
        record["candidate_selection"]["selection_signals"]["prerequisite_matches"] = [{
            "pattern": "strong_dependency_term",
            "connector": "dependent on",
            "span": [start, start + len("dependent on")],
            "confidence": "provisional_high",
        }]
        output = annotate_record(record)
        annotation = output["text2task_annotations"]
        self.assertIn("EVENT", {entity["type"] for entity in annotation["entities"]})
        self.assertIn("DEPENDS_ON", {relation["type"] for relation in annotation["relations"]})
        self.assertEqual(validate_record(output, require_annotations=True), [])


if __name__ == "__main__":
    unittest.main()
