import unittest

from src.baselines.rule_based import extract_spans, spans_to_bio


def texts(text):
    return {(t, text[s:e]) for t, s, e in extract_spans(text)}


class RuleBasedTests(unittest.TestCase):
    def test_temporal_expressions(self):
        got = texts("Please send it by Friday or on March 23, 2001 at 3:30 pm, not tomorrow.")
        for expected in [("TEMPORAL", "Friday"), ("TEMPORAL", "March 23, 2001"), ("TEMPORAL", "3:30 pm"), ("TEMPORAL", "tomorrow")]:
            self.assertIn(expected, got)

    def test_bare_may_is_not_a_date(self):
        self.assertEqual(set(), {x for x in texts("You may want to look.") if x[0] == "TEMPORAL"})

    def test_task_is_cut_before_date(self):
        got = texts("Please send the report by Friday.")
        self.assertIn(("TASK", "Please send the report"), got)
        self.assertIn(("TEMPORAL", "Friday"), got)

    def test_commitment_and_let_me_know(self):
        got = texts("I will review the draft. Let me know if you have questions.")
        self.assertTrue(any(t == "TASK" and x.startswith("will review") for t, x in got))
        self.assertTrue(any(t == "TASK" and x.startswith("Let me know") for t, x in got))

    def test_person_from_salutation(self):
        self.assertIn(("PERSON", "Kim"), texts("Kim, please call the office."))

    def test_non_task_text_has_no_task(self):
        self.assertEqual(set(), {x for x in texts("The meeting went well and the numbers look fine.") if x[0] == "TASK"})

    def test_spans_do_not_overlap(self):
        spans = extract_spans("Hi Bob, please call Jim tomorrow and send the file on Friday.")
        for i, a in enumerate(spans):
            for b in spans[i + 1:]:
                self.assertFalse(a[1] < b[2] and b[1] < a[2], (a, b))

    def test_spans_to_bio(self):
        offsets = [[0, 3], [4, 7], [8, 12], [13, 15]]
        self.assertEqual(["O", "B-TASK", "I-TASK", "O"], spans_to_bio(offsets, [("TASK", 4, 12)]))


if __name__ == "__main__":
    unittest.main()
