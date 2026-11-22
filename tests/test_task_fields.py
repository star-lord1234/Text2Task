import json
import unittest

from src.pipeline.contracts import MessageEnvelope, Participant
from src.pipeline.identity_resolution import ParticipantRegistry
from src.pipeline.task_fields import build_task_candidates
from src.pipeline.uncertainty import load_config

REG = ParticipantRegistry([Participant("riya", "Riya Sharma", ["Riya"]), Participant("bianca", "Bianca Sawant", ["Bianca"]),
                           Participant("dev", "Dev Patel", [])])
TS, TZ = "2026-11-11T09:30:00", "America/Chicago"


def ent(text, span, typ, eid):
    s = text.index(span)
    return {"id": eid, "type": typ, "start": s, "end": s + len(span), "text": span}


def rel(src, tgt, label, score=0.95, prov="neural"):
    return {"source_id": src, "target_id": tgt, "label": label, "score": score, "provenance": prov, "model_version": "test"}


def env(text, ts=TS, tz=TZ, recipients=("riya",)):
    return MessageEnvelope("m1", text, "bianca", list(recipients), ts, tz)


TEXT = "Riya, please submit the report by Friday."
ENTS = [ent(TEXT, "Riya", "PERSON", "p"), ent(TEXT, "submit the report", "TASK", "t"), ent(TEXT, "Friday", "TEMPORAL", "d")]


def codes(c):
    return [f.code for f in c.flags]


class AssemblyTests(unittest.TestCase):
    def test_deadline_cue_reinterpreted_and_flagged_not_silent(self):
        (c,) = build_task_candidates(env(TEXT), ENTS, [rel("t", "p", "ASSIGNED_TO"), rel("t", "d", "SCHEDULED_ON", 0.97)], REG)
        self.assertEqual(c.assignee.participant_id, "riya")
        self.assertEqual(c.due.value, "2026-11-13")
        self.assertIsNone(c.scheduled)
        self.assertIn("DATE_RELATION_CONFLICT", codes(c))
        self.assertTrue(c.review_required)
        note = c.provenance["label_reinterpretations"][0]
        self.assertEqual((note["model_label"], note["applied_label"]), ("SCHEDULED_ON", "DUE_ON"))

    def test_due_on_stays_due_without_conflict(self):
        (c,) = build_task_candidates(env(TEXT), ENTS, [rel("t", "p", "ASSIGNED_TO"), rel("t", "d", "DUE_ON")], REG)
        self.assertEqual(c.due.value, "2026-11-13")
        self.assertNotIn("DATE_RELATION_CONFLICT", codes(c))
        self.assertEqual(c.provenance["label_reinterpretations"], [])
        self.assertFalse(c.review_required)

    def test_unresolved_date_survives_without_timestamp(self):
        (c,) = build_task_candidates(env(TEXT, ts=None, tz=None), ENTS, [rel("t", "p", "ASSIGNED_TO"), rel("t", "d", "DUE_ON")], REG)
        self.assertEqual(c.due.status, "UNRESOLVED_NO_ANCHOR")
        self.assertEqual(c.due.raw, "Friday")
        self.assertIsNone(c.due.value)
        self.assertIn("DATE_UNRESOLVED_NO_ANCHOR", codes(c))
        self.assertTrue(c.review_required)
        self.assertIn("Friday", [f.question for f in c.flags if f.code == "DATE_UNRESOLVED_NO_ANCHOR"][0])

    def test_unlinked_task_is_kept_with_no_assignee_flag(self):
        t = "The report was filed yesterday."
        (c,) = build_task_candidates(env(t), [ent(t, "filed", "TASK", "t")], [], REG)
        self.assertEqual(c.assignee.status, "UNASSIGNED")
        self.assertIsNone(c.due)
        self.assertIsNone(c.scheduled)
        self.assertIn("NO_ASSIGNEE", codes(c))
        self.assertTrue(c.review_required)

    def test_due_and_scheduled_are_separate(self):
        t = "Riya, please prepare slides by Friday and present on Monday at 10."
        e = [ent(t, "Riya", "PERSON", "p"), ent(t, "prepare slides", "TASK", "t"), ent(t, "Friday", "TEMPORAL", "d1"),
             ent(t, "Monday", "TEMPORAL", "d2"), ent(t, "10", "TEMPORAL", "d3")]
        (c,) = build_task_candidates(env(t), e, [rel("t", "p", "ASSIGNED_TO"), rel("t", "d1", "DUE_ON"),
                                                  rel("t", "d2", "SCHEDULED_ON", 0.9), rel("t", "d3", "SCHEDULED_ON", 0.8)], REG)
        self.assertEqual(c.due.value, "2026-11-13")
        self.assertEqual(c.scheduled.value, "2026-11-16T10:00:00-06:00")  # date + time merged
        self.assertNotIn("COMPETING_DATES", codes(c))

    def test_competing_dates_flag_keeps_higher_score(self):
        t = "Send the report by Friday or by Monday."
        e = [ent(t, "Send the report", "TASK", "t"), ent(t, "Friday", "TEMPORAL", "d1"), ent(t, "Monday", "TEMPORAL", "d2")]
        (c,) = build_task_candidates(env(t), e, [rel("t", "d1", "DUE_ON", 0.9), rel("t", "d2", "DUE_ON", 0.6)], REG)
        self.assertEqual(c.due.value, "2026-11-13")
        self.assertIn("COMPETING_DATES", codes(c))

    def test_disagreement_flag(self):
        neural = [rel("t", "p", "ASSIGNED_TO")]
        rules = [rel("t", "d", "DUE_ON", prov="rule")]
        (c,) = build_task_candidates(env(TEXT), ENTS, neural, REG, comparator_relations=rules)
        self.assertIn("MODEL_DISAGREEMENT", codes(c))
        (c2,) = build_task_candidates(env(TEXT), ENTS, neural, REG, comparator_relations=list(neural))
        self.assertNotIn("MODEL_DISAGREEMENT", codes(c2))

    def test_weak_score_flag_respects_threshold(self):
        cfg = load_config()
        cfg["uncertainty"]["min_relation_score"] = 0.9
        (c,) = build_task_candidates(env(TEXT), ENTS, [rel("t", "p", "ASSIGNED_TO", 0.55)], REG, config=cfg)
        self.assertIn("WEAK_RELATION_SCORE", codes(c))
        cfg["uncertainty"]["min_relation_score"] = 0.0   # 0.0 disables weak-score flagging
        (c0,) = build_task_candidates(env(TEXT), ENTS, [rel("t", "p", "ASSIGNED_TO", 0.55)], REG, config=cfg)
        self.assertNotIn("WEAK_RELATION_SCORE", codes(c0))
        (cd,) = build_task_candidates(env(TEXT), ENTS, [rel("t", "p", "ASSIGNED_TO", 0.55)], REG)  # shipped default (0.9)
        self.assertIn("WEAK_RELATION_SCORE", codes(cd))

    def test_relations_without_a_score_are_unknown_not_weak_and_not_a_crash(self):
        # scripted fixtures and rules carry score=None: it must neither crash nor be treated as a weak (or perfect) score
        unscored = [{**rel("t", "p", "ASSIGNED_TO"), "score": None}, {**rel("t", "d", "DUE_ON"), "score": None}]
        (c,) = build_task_candidates(env(TEXT), ENTS, unscored, REG)
        self.assertNotIn("WEAK_RELATION_SCORE", codes(c))
        self.assertEqual(c.due.value, "2026-11-13")
        self.assertEqual(c.assignee.participant_id, "riya")

    def test_dependency_is_proposed_not_accepted_and_missing_target_flagged(self):
        t = "Publish the notes after approve the draft."
        e = [ent(t, "Publish the notes", "TASK", "a"), ent(t, "approve the draft", "TASK", "b")]
        cands = build_task_candidates(env(t), e, [rel("a", "b", "DEPENDS_ON", 1.0, "rule")], REG, primary_source="rule")
        a = cands[0]
        self.assertEqual(a.dependencies[0]["status"], "proposed")
        self.assertEqual(a.dependencies[0]["prerequisite_candidate_id"], cands[1].candidate_id)
        (c,) = build_task_candidates(env(t), [e[0]], [rel("a", "ghost", "DEPENDS_ON", 1.0, "rule")], REG, primary_source="rule")
        self.assertIn("UNSUPPORTED_PREREQUISITE", codes(c))

    def test_json_roundtrip_and_deterministic_ids(self):
        r1 = build_task_candidates(env(TEXT), ENTS, [rel("t", "p", "ASSIGNED_TO")], REG)
        r2 = build_task_candidates(env(TEXT), ENTS, [rel("t", "p", "ASSIGNED_TO")], REG)
        self.assertEqual(r1[0].candidate_id, r2[0].candidate_id)
        self.assertEqual(json.loads(json.dumps(r1[0].to_dict()))["title"], "submit the report")


if __name__ == "__main__":
    unittest.main()
