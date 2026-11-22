import unittest

from src.pipeline.contracts import AssigneeResolution
from src.pipeline.uncertainty import (TEMPLATES, assignee_flags, load_config, make_flag, review_required, temporal_flags)
from src.temporal.normalize import normalize_temporal

CFG = load_config()
REF, TZ = "2026-11-11T09:30:00", "America/Chicago"


def codes(flags):
    return [f.code for f in flags]


class FlagTests(unittest.TestCase):
    def test_every_template_formats(self):
        for code in TEMPLATES:
            f = make_flag(code, "x", CFG, raw="r", candidates="a, b", missing="year", assumptions="z", value="v", label="DUE_ON", cue="by", score=0.5, task="do it")
            self.assertTrue(f.message and f.question, code)

    def test_no_anchor_flag_with_question(self):
        tv = normalize_temporal("Friday")
        f = temporal_flags(tv, "due", "DUE_ON", "", CFG)
        self.assertIn("DATE_UNRESOLVED_NO_ANCHOR", codes(f))
        self.assertIn("Friday", [x for x in f if x.code == "DATE_UNRESOLVED_NO_ANCHOR"][0].question)

    def test_ambiguous_weekday(self):
        tv = normalize_temporal("Wednesday", reference_ts=REF, timezone=TZ)
        f = temporal_flags(tv, "due", "DUE_ON", "", CFG)
        q = [x for x in f if x.code == "DATE_AMBIGUOUS"][0].question
        self.assertIn("2026-11-11", q)
        self.assertIn("2026-11-18", q)

    def test_event_vague_unparseable_partial(self):
        for raw, code in [("after approval", "DATE_EVENT_CONDITION"), ("soon", "DATE_VAGUE"), ("blah blah", "DATE_UNPARSEABLE"), ("5pm", "DATE_PARTIAL")]:
            f = temporal_flags(normalize_temporal(raw, reference_ts=REF, timezone=TZ), "due", "DUE_ON", "", CFG)
            self.assertIn(code, codes(f), raw)

    def test_label_conflict_only_with_deadline_cue(self):
        tv = normalize_temporal("Friday", reference_ts=REF, timezone=TZ)
        self.assertIn("DATE_RELATION_CONFLICT", codes(temporal_flags(tv, "due", "SCHEDULED_ON", "submit the report by ", CFG)))
        self.assertNotIn("DATE_RELATION_CONFLICT", codes(temporal_flags(tv, "scheduled", "SCHEDULED_ON", "we will meet on ", CFG)))
        self.assertNotIn("DATE_RELATION_CONFLICT", codes(temporal_flags(tv, "due", "DUE_ON", "by ", CFG)))

    def test_past_date(self):
        tv = normalize_temporal("yesterday", reference_ts=REF, timezone=TZ)
        self.assertIn("PAST_DATE", codes(temporal_flags(tv, "scheduled", "SCHEDULED_ON", "", CFG)))

    def test_info_only_flags_do_not_require_review(self):
        tv = normalize_temporal("Monday at 2:30 pm", reference_ts=REF, timezone=TZ)
        flags = temporal_flags(tv, "scheduled", "SCHEDULED_ON", "meet ", CFG)
        self.assertEqual(flags, [])
        tv = normalize_temporal("Monday at 10", reference_ts=REF, timezone=TZ)
        flags = temporal_flags(tv, "scheduled", "SCHEDULED_ON", "meet ", CFG)
        self.assertEqual(codes(flags), ["DATE_ASSUMPTION"])
        self.assertFalse(review_required(flags))

    def test_floating_timezone_flag(self):
        tv = normalize_temporal("tomorrow at 10am", reference_ts=REF)
        self.assertIn("TZ_ASSUMED", codes(temporal_flags(tv, "due", "DUE_ON", "", CFG)))

    def test_assignee_flags(self):
        cases = [(AssigneeResolution(None, "UNASSIGNED", basis="no_assignee_evidence"), "NO_ASSIGNEE"),
                 (AssigneeResolution("Anna", "AMBIGUOUS", candidates=["a", "b"], basis="name_token_shared"), "AMBIGUOUS_ASSIGNEE"),
                 (AssigneeResolution("A | B", "AMBIGUOUS", candidates=["a", "b"], basis="multiple_assignees"), "MULTIPLE_ASSIGNEES"),
                 (AssigneeResolution("Zed", "UNKNOWN_PERSON"), "UNKNOWN_PERSON"),
                 (AssigneeResolution("all", "UNSUPPORTED_GROUP"), "UNSUPPORTED_GROUP"),
                 (AssigneeResolution(None, "UNASSIGNED", candidates=["a", "b"], basis="multiple_recipients"), "AMBIGUOUS_ASSIGNEE")]
        for a, code in cases:
            self.assertIn(code, codes(assignee_flags(a, "do it", CFG)))
        self.assertEqual(assignee_flags(AssigneeResolution("Riya", "RESOLVED", "riya", basis="exact_alias"), "do it", CFG), [])


if __name__ == "__main__":
    unittest.main()
