import unittest

from src.baselines.rule_relations import predict_rules


def ent(text, span, typ, i):
    start = text.index(span)
    return {"id": i, "type": typ, "start": start, "end": start + len(span), "text": span}


class RuleRelationTests(unittest.TestCase):
    def labels(self, text, ents):
        return sorted((r["source_id"], r["target_id"], r["label"]) for r in predict_rules(text, ents)["relations"])

    def test_addressee_assignment(self):
        t = "Riya, please submit the report by Friday."
        e = [ent(t, "Riya", "PERSON", "p"), ent(t, "submit the report", "TASK", "t"), ent(t, "by Friday", "TEMPORAL", "d")]
        self.assertEqual(self.labels(t, e), [("t", "d", "DUE_ON"), ("t", "p", "ASSIGNED_TO")])

    def test_scheduled_vs_deadline(self):
        t = "We will review the report on Monday at 10."
        e = [ent(t, "review the report", "TASK", "t"), ent(t, "Monday at 10", "TEMPORAL", "d")]
        self.assertEqual(self.labels(t, e), [("t", "d", "SCHEDULED_ON")])

    def test_nearest_person_wins(self):
        t = "Anna Bob review it."
        e = [ent(t, "Anna", "PERSON", "a"), ent(t, "Bob", "PERSON", "b"), ent(t, "review it", "TASK", "t")]
        res = predict_rules(t, e)
        self.assertEqual([r for r in res["relations"] if r["label"] == "ASSIGNED_TO"][0]["target_id"], "b")

    def test_no_assignee_no_link(self):
        t = "The report was filed. Riya went home."
        e = [ent(t, "filed", "TASK", "t"), ent(t, "Riya", "PERSON", "p")]
        self.assertEqual(self.labels(t, e), [])

    def test_temporal_in_other_sentence_not_linked(self):
        t = "Submit the report. See you Friday."
        e = [ent(t, "Submit the report", "TASK", "t"), ent(t, "Friday", "TEMPORAL", "d")]
        self.assertEqual(self.labels(t, e), [])

    def test_depends_on_requires_explicit_cue(self):
        t = "Publish the notes after approve the draft."
        e = [ent(t, "Publish the notes", "TASK", "a"), ent(t, "approve the draft", "TASK", "b")]
        self.assertEqual(self.labels(t, e), [("a", "b", "DEPENDS_ON")])
        t2 = "Publish the notes, approve the draft."
        e2 = [ent(t2, "Publish the notes", "TASK", "a"), ent(t2, "approve the draft", "TASK", "b")]
        self.assertEqual(self.labels(t2, e2), [])


if __name__ == "__main__":
    unittest.main()
