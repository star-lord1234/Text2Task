import unittest

from src.annotation.mailex_labels import (
    build_entities, char_range, is_commitment, is_event_clause_not_time, is_person_name, load_mapping,
    parse_event_spans,
)

MAPPING = load_mapping("configs/mailex_to_text2task_v1.json")


def record(text, tokens, events):
    offsets, pos = [], 0
    for token in tokens:
        start = text.index(token, pos)
        offsets.append([start, start + len(token)])
        pos = start + len(token)
    return {"text": text, "tokens": tokens, "token_offsets": offsets, "original_events": events}


def labels(n, spans):
    out = ["O"] * n
    for event, slot, start, end in spans:
        out[start] = f"{event}:B-{slot}"
        for i in range(start + 1, end):
            out[i] = f"{event}:I-{slot}"
    return out


class PersonFilterTests(unittest.TestCase):
    cfg = MAPPING["person"]

    def test_accepts_names(self):
        for name in ["Kim", "Jeff Skilling", "McIntosh", "Kathy R."]:
            self.assertTrue(is_person_name(name, self.cfg), name)

    def test_rejects_pronouns_companies_roles(self):
        for name in ["you", "We", "PSCo", "Yahoo", "Plant Operators", "Bear Stearns", "FERC", "Mom", "G", "the team"]:
            self.assertFalse(is_person_name(name, self.cfg), name)

    def test_keeps_names_that_resemble_company_words(self):
        for name in ["Charles Yeung", "Arthur", "Douglas"]:
            self.assertTrue(is_person_name(name, self.cfg), name)


class CommitmentTests(unittest.TestCase):
    cfg = MAPPING["task"]

    def test_commitments(self):
        for text in ["will send to legal", "'ll check with Shirley", "are going change out a meter",
                     "will be forwarding to legal the docs", "is going to review it"]:
            self.assertTrue(is_commitment(text, self.cfg), text)

    def test_states_are_not_commitments(self):
        for text in ["will be charged $ 50", "will be out of the office", "has been given the charge",
                     "will not accept either", "received the amendment", "will have all the pieces"]:
            self.assertFalse(is_commitment(text, self.cfg), text)


class TemporalClauseTests(unittest.TestCase):
    cfg = MAPPING["temporal"]

    def test_event_clauses_rejected(self):
        for text in ["Upon her approval", "once an GSA is completed", "by the time we calc our books",
                     "prior to agreeing on any further changes", "when done"]:
            self.assertTrue(is_event_clause_not_time(text, self.cfg), text)

    def test_real_times_kept(self):
        for text in ["before the end of the day", "by 3pm", "after 5 p.m.", "Monday", "until Friday", "next week"]:
            self.assertFalse(is_event_clause_not_time(text, self.cfg), text)


class BuildEntitiesTests(unittest.TestCase):
    def test_request_maps_to_task_and_offsets(self):
        text = "Please send the report by Friday ."
        tokens = text.split(" ")
        events = {"Request_Action": {"labels": [labels(len(tokens), [
            ("Request_Action", "Action Description", 1, 4), ("Request_Action", "Action Date", 4, 6)])],
            "triggers": [], "extras": []}}
        rec = record(text, tokens, events)
        entities, _, _ = build_entities(rec, MAPPING)
        got = {(e["type"], e["text"]) for e in entities}
        self.assertEqual({("TASK", "send the report"), ("TEMPORAL", "by Friday")}, got)

    def test_deliver_action_is_not_task_unless_commitment(self):
        text = "I received the file . We will send it ."
        tokens = text.split(" ")
        events = {"Deliver_Action_Data": {"labels": [labels(len(tokens), [
            ("Deliver_Action_Data", "Action Description", 1, 4),
            ("Deliver_Action_Data", "Action Description", 6, 9)])], "triggers": [], "extras": []}}
        rec = record(text, tokens, events)
        with_c, _, _ = build_entities(rec, MAPPING, include_commitments=True)
        without_c, _, _ = build_entities(rec, MAPPING, include_commitments=False)
        self.assertEqual(["will send it"], [e["text"] for e in with_c if e["type"] == "TASK"])
        self.assertEqual([], [e for e in without_c if e["type"] == "TASK"])

    def test_person_propagates_but_not_inside_other_spans(self):
        text = "Hi Kim please ask Kim today ."
        tokens = text.split(" ")
        events = {"Request_Action": {"labels": [labels(len(tokens), [
            ("Request_Action", "Action Members", 1, 2), ("Request_Action", "Action Description", 3, 5)])],
            "triggers": [], "extras": []}}
        entities, _, _ = build_entities(record(text, tokens, events), MAPPING)
        persons = [e for e in entities if e["type"] == "PERSON"]
        self.assertEqual(1, len(persons))  # the second Kim is inside the TASK span, so it is not propagated

    def test_parse_and_char_range_skip_zero_width(self):
        rec = {"text": "ab cd", "tokens": ["ab", [], "cd"], "token_offsets": [[0, 2], [3, 3], [3, 5]],
               "original_events": {}}
        self.assertEqual((0, 5), char_range(rec, 0, 3))
        self.assertEqual([], parse_event_spans(rec))


if __name__ == "__main__":
    unittest.main()
