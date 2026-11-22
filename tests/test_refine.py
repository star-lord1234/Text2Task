"""Phase 7.5 refinement: positive AND negative regression tests on synthetic neural output (no model needed).
Every stage is also checked to be independently switchable and to leave the raw neural output untouched."""
import unittest

from src.reconciliation.cues import split_sentences
from src.refine.clauses import extract_clause_dependencies
from src.refine.config import PRESETS, RefineConfig, from_preset, resolve
from src.refine.grammar import find_action_phrases, has_verb, is_state_clause, roster_mentions
from src.refine.pipeline import refine
from src.refine.relations import refine_relations
from src.refine.spans import filter_invalid, merge_adjacent, snap, tag_neural
from src.refine.temporal import detect

PEOPLE = [{"id": "riya", "name": "Riya"}, {"id": "anushree", "name": "Anushree"}, {"id": "bianca", "name": "Bianca"}]
NAMES = ["riya", "anushree", "bianca"]


def ents(text, *spans):
    out = []
    for i, (typ, sub) in enumerate(spans):
        a = text.index(sub)
        out.append({"id": f"pred-e{i}", "type": typ, "start": a, "end": a + len(sub), "text": sub, "confidence": 0.9})
    return out


def texts(es, typ=None):
    return [e["text"] for e in es if typ is None or e["type"] == typ]


class ConfigTests(unittest.TestCase):
    def test_presets_resolve_and_neural_only_changes_nothing(self):
        self.assertFalse(from_preset("neural_only").any_refinement)
        self.assertFalse(from_preset("neural_only").rule_dependency_linker)
        self.assertTrue(from_preset("hybrid").any_refinement)
        self.assertEqual(from_preset("rule_only").entity_source, "rule")
        self.assertEqual(set(PRESETS), {"neural_only", "neural_plus_linker", "refined", "hybrid", "rule_only"})

    def test_overrides_win_and_are_reported(self):
        c = resolve({"pipeline_preset": "hybrid", "refine_overrides": {"clause_dependencies": False}})
        self.assertFalse(c.clause_dependencies)
        self.assertTrue(c.span_snap)
        self.assertEqual(c.preset, "hybrid+custom")

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError):
            from_preset("nope")

    def test_no_refinement_returns_the_raw_entities_unchanged(self):
        t = "I'll send the invoice tomorrow."
        raw = ents(t, ("TASK", "send the"), ("TASK", "ice"))
        r = refine(t, raw, from_preset("neural_only"), PEOPLE)
        self.assertEqual([e["text"] for e in r.entities], ["send the", "ice"])
        self.assertTrue(all(e["origin"] == "neural" for e in r.entities))
        self.assertEqual(r.trace, [])


class SpanTests(unittest.TestCase):
    def test_snap_extends_a_span_that_ends_inside_a_word(self):
        t = "Please send the invoice now."
        e = ents(t, ("TASK", "send the inv"))
        out = snap(t, tag_neural(e), [])
        self.assertEqual(out[0]["text"], "send the invoice")
        self.assertEqual(out[0]["origin"], "refined")
        self.assertEqual(out[0]["refinement"][0]["op"], "snap_to_word")

    def test_snap_leaves_word_aligned_spans_alone(self):
        t = "Please send the invoice now."
        out = snap(t, tag_neural(ents(t, ("TASK", "send the invoice"))), [])
        self.assertEqual(out[0]["origin"], "neural")
        self.assertEqual(out[0]["refinement"], [])

    def test_snap_does_not_run_into_a_different_entity(self):
        t = "Bianca,please send it"
        e = [{"id": "p", "type": "PERSON", "start": 0, "end": 5, "text": "Bianc", "confidence": 0.9},
             {"id": "k", "type": "TASK", "start": 5, "end": len(t), "text": t[5:], "confidence": 0.9}]       # a truncated name beside a task span
        out = snap(t, tag_neural(e), [])
        self.assertEqual([x["text"] for x in out], ["Bianc", "a,please send it"])                         # neither may swallow the other

    def test_filter_drops_function_word_fragments_but_keeps_real_phrases(self):
        t = "x"
        keep = {"id": "k", "type": "TASK", "start": 0, "end": 1, "text": "send the invoice"}
        for frag in ("once", "the", "after you", "only after", "please", "can", "need", "Let me"):
            e = {"id": "f", "type": "TASK", "start": 0, "end": 1, "text": frag}
            self.assertEqual(filter_invalid(t, [e], []), [], frag)
        self.assertEqual(filter_invalid(t, [keep], []), [keep])
        self.assertEqual(len(filter_invalid(t, [dict(keep, text="please train the")], [])), 1)     # has a verb: kept (dangling, repaired later)
        self.assertEqual(filter_invalid(t, [dict(keep, text="the dataset")], []), [])             # determiner-led noun phrase, no verb
        self.assertEqual(filter_invalid(t, [dict(keep, text="after the dataset")], []), [])
        self.assertEqual(len(filter_invalid(t, [dict(keep, text="the report is late")], [])), 1)  # has an auxiliary: not a bare noun phrase

    def test_filter_never_touches_person_or_temporal(self):
        e = [{"id": "p", "type": "PERSON", "start": 0, "end": 1, "text": "the"}, {"id": "t", "type": "TEMPORAL", "start": 0, "end": 1, "text": "by"}]
        self.assertEqual(filter_invalid("x", e, []), e)

    def test_merge_adjacent_joins_whitespace_separated_same_type_spans(self):
        t = "send the invoice"
        out = merge_adjacent(t, ents(t, ("TASK", "send the"), ("TASK", "invoice")), [])
        self.assertEqual(texts(out), ["send the invoice"])

    def test_merge_does_not_join_across_words_or_types(self):
        t = "train the once model"
        self.assertEqual(len(merge_adjacent(t, ents(t, ("TASK", "train the"), ("TASK", "model")), [])), 2)       # 'once' sits between
        t2 = "Bianca send"
        self.assertEqual(len(merge_adjacent(t2, ents(t2, ("PERSON", "Bianca"), ("TASK", "send")), [])), 2)

    def test_identical_fragments_of_one_word_collapse(self):
        t = "someone proofread it"
        a = ents(t, ("TASK", "proof"))[0]
        b = dict(a, id="b", start=a["start"] + 5, end=a["start"] + 6, text="d")        # 'proof' + 'd' both snap to 'proofread'
        out = merge_adjacent(t, snap(t, [a, b], []), [])
        self.assertEqual(texts(out), ["proofread"])


class TemporalTests(unittest.TestCase):
    def test_detects_and_merges_compatible_atoms(self):
        cases = {"report by Friday.": "by Friday", "present on Monday at 3pm.": "on Monday at 3pm", "room for next Tuesday afternoon.": "for next Tuesday afternoon",
                 "finish by end of day tomorrow": "by end of day tomorrow", "meet on Nov 12th at 14:30": "on Nov 12th at 14:30", "due 2026-11-13": "due 2026-11-13"}
        for text, want in cases.items():
            got = [x["text"] for x in detect(text)]
            self.assertEqual(got, [want], text)

    def test_two_dates_do_not_merge(self):
        self.assertEqual([x["text"] for x in detect("Thursday and Friday work")], ["Thursday", "Friday"])
        self.assertEqual([x["text"] for x in detect("by Thursday and the invoice by Friday")], ["by Thursday", "by Friday"])

    def test_non_temporal_words_are_not_detected(self):
        for text in ("I sat down and may go.", "The server crashed.", "Great job on the launch", "Release notes are ready"):
            self.assertEqual(detect(text), [], text)

    def test_merge_fixes_a_split_deadline_and_adds_a_missed_date(self):
        t = "Bianca, send it by Friday and call me Monday morning."
        raw = ents(t, ("PERSON", "Bianca"), ("TEMPORAL", "by"))
        raw.append({"id": "pred-e9", "type": "TEMPORAL", "start": t.index("Friday"), "end": t.index("Friday") + 6, "text": "Friday", "confidence": 0.8})
        r = refine(t, raw, from_preset("refined"), PEOPLE)
        got = {e["text"]: e["origin"] for e in r.entities if e["type"] == "TEMPORAL"}
        self.assertEqual(got, {"by Friday": "refined", "Monday morning": "rule"})
        merged = next(e for e in r.entities if e["text"] == "by Friday")
        self.assertEqual(merged["neural_ids"], ["pred-e1", "pred-e9"])

    def test_merge_and_detect_are_independent_switches(self):
        t = "send it by Friday"
        raw = ents(t, ("TEMPORAL", "by"))
        only_detect = RefineConfig(temporal_detect=True)
        r = refine(t, raw, only_detect, PEOPLE)
        self.assertEqual(texts(r.entities, "TEMPORAL"), ["by"])                 # overlapping neural span is not merged without temporal_merge
        only_merge = refine(t, raw, RefineConfig(temporal_merge=True), PEOPLE)
        self.assertEqual(texts(only_merge.entities, "TEMPORAL"), ["by Friday"])

    def test_a_far_reaching_neural_span_is_kept(self):
        t = "We could meet Friday if that suits everyone involved here."
        raw = ents(t, ("TEMPORAL", "Friday if that suits everyone"))
        r = refine(t, raw, from_preset("refined"), PEOPLE)
        self.assertEqual(texts(r.entities, "TEMPORAL"), ["Friday if that suits everyone"])


class GrammarTests(unittest.TestCase):
    def phrases(self, text, **kw):
        return [p.text for p in find_action_phrases(text, names=NAMES, **kw)]

    def test_finds_action_phrases_by_position(self):
        self.assertEqual(self.phrases("Bianca, please prepare the report."), ["prepare the report"])
        self.assertEqual(self.phrases("Anushree, can you clean the dataset?"), ["clean the dataset"])
        self.assertEqual(self.phrases("Someone needs to proofread it."), ["proofread it"])
        self.assertEqual(self.phrases("Someone should back up the database."), ["back up the database"])
        self.assertEqual(self.phrases("Let me fix the login bug."), ["fix the login bug"])
        self.assertEqual(self.phrases("After you clean the dataset, write a report."), ["clean the dataset", "write a report"])

    def test_stops_at_protected_spans(self):
        t = "Bianca, please book a room for next Tuesday afternoon."
        a = t.index("for next")
        self.assertEqual(self.phrases(t, protected=[(a, len(t) - 1)]), ["book a room"])

    def test_no_phrase_in_statements_questions_or_noun_phrases(self):
        for t in ("The server went down yesterday.", "Release notes are due Friday.", "Thanks for sending the invoice.", "Great job on the launch, everyone!",
                  "Lunch is at noon in the kitchen.", "Did you see the report?", "We shipped the release yesterday.", "The meeting was cancelled.",
                  "Anushree finished the dataset.", "The report has been sent."):
            self.assertEqual(self.phrases(t), [], t)

    def test_generic_commitments_are_acknowledgements_not_tasks(self):
        for t in ("Sure, I'll take care of it.", "I'll handle that.", "I can do it."):
            self.assertEqual(self.phrases(t), [], t)

    def test_state_clauses(self):
        for c in ("the dataset is cleaned", "Anushree has collected the responses", "the test server is set up", "it is ready"):
            self.assertTrue(is_state_clause(c), c)
        for c in ("you clean the dataset", "Anushree finishes the dataset", "write a report", "the meeting"):
            self.assertFalse(is_state_clause(c), c)

    def test_has_verb_tolerates_inflection(self):
        self.assertTrue(has_verb("finishes the draft"))
        self.assertFalse(has_verb("the dataset"))

    def test_roster_names_only_as_vocative_or_subject(self):
        pid = {"bianca": "bianca", "anushree": "anushree"}
        self.assertEqual([p for *_, p in roster_mentions("Bianca, please send it.", pid, [])], ["bianca"])
        self.assertEqual([p for *_, p in roster_mentions("Then Anushree should evaluate it.", pid, [])], ["anushree"])
        self.assertEqual(roster_mentions("Send it to Bianca.", pid, []), [])                           # object, not an assignee
        self.assertEqual(roster_mentions("Train the model once Anushree finishes the dataset.", pid, []), [])   # inside a condition
        self.assertEqual(roster_mentions("Bianca, please send it.", pid, [(0, 6)]), [])                 # already covered by an entity


class ClauseTests(unittest.TestCase):
    def deps(self, text, tasks=()):
        return extract_clause_dependencies(text, split_sentences(text), list(tasks), [], NAMES)

    def shape(self, text):
        return [(d.pattern, d.dependent.kind, d.prerequisite.kind) for d in self.deps(text)]

    def test_constructions(self):
        self.assertEqual(self.shape("After you clean the dataset, write a report."), [("cue_first", "task", "task")])
        self.assertEqual(self.shape("Anushree, after you clean the dataset, please write a report."), [("cue_first", "task", "task")])
        self.assertEqual(self.shape("Before we send the report, someone needs to proofread it."), [("before_first", "task", "task")])
        self.assertEqual(self.shape("Please finalize the budget before sending it to finance."), [("before_after", "task", "task")])
        self.assertEqual(self.shape("Bianca, please train the model, then Anushree should evaluate it."), [("sequence", "task", "task")])
        self.assertEqual(self.shape("First export the data, then clean it, and then train the model."), [("sequence", "task", "task")] * 2)

    def test_direction_later_step_depends_on_earlier(self):
        d = self.deps("Before we send the report, someone needs to proofread it.")[0]
        self.assertEqual((d.dependent.phrase.text, d.prerequisite.phrase.text), ("send the report", "proofread it"))
        d = self.deps("Bianca, train the model, then Anushree should evaluate it.")[0]
        self.assertEqual((d.dependent.phrase.text, d.prerequisite.phrase.text), ("evaluate it", "train the model"))

    def test_state_and_completion_clauses_are_references_to_existing_work(self):
        for t in ("Bianca, train the model after the dataset is cleaned.", "Bianca, train the model once Anushree finishes the dataset.",
                  "Bianca, analyse the results after Anushree has collected the responses."):
            self.assertEqual([(d.dependent.kind, d.prerequisite.kind) for d in self.deps(t)], [("task", "reference")], t)

    def test_blocked_statement_links_two_references(self):
        self.assertEqual(self.shape("Deployment can't start until the test server is set up."), [("cue_after", "reference", "reference")])

    def test_no_dependency_from_times_events_or_vague_clauses(self):
        for t in ("Bianca, send it after 3pm.", "Bianca, send it before Friday.", "Bianca, update the wiki when you get a chance.",
                  "Release notes are due after the freeze.", "Bianca, please write the report by Friday.", "The server went down yesterday."):
            self.assertEqual(self.deps(t), [], t)

    def test_dependent_must_be_a_task(self):
        self.assertEqual(self.deps("After the meeting, lunch."), [])
        self.assertEqual(self.deps("Once the design is approved, the budget."), [])

    def test_pipeline_emits_relations_only_between_two_tasks_and_hints_for_references(self):
        t = "After you clean the dataset, write a report."
        r = refine(t, ents(t, ("TASK", "After you"), ("TASK", "write a report")), from_preset("hybrid"), PEOPLE)
        self.assertEqual([(x["label"], x["provenance"], x["rule"]) for x in r.relations], [("DEPENDS_ON", "rule", "clause:cue_first")])
        self.assertEqual(r.hints, [])
        dep = next(e for e in r.entities if e["id"] == r.relations[0]["source_id"])
        pre = next(e for e in r.entities if e["id"] == r.relations[0]["target_id"])
        self.assertEqual((dep["text"], pre["text"]), ("write a report", "clean the dataset"))
        t2 = "Bianca, train the model after the dataset is cleaned."
        r2 = refine(t2, ents(t2, ("PERSON", "Bianca"), ("TASK", "train the"), ("TASK", "after the dataset"), ("TASK", "cleaned")), from_preset("hybrid"), PEOPLE)
        self.assertEqual(r2.relations, [])
        self.assertEqual([h["kind"] for h in r2.hints], ["task_reference"])
        self.assertEqual(texts(r2.entities, "TASK"), ["train the model"])              # fragments of the condition clause are not tasks
        t3 = "Bianca, call me after the meeting."
        r3 = refine(t3, ents(t3, ("PERSON", "Bianca"), ("TASK", "call me")), from_preset("hybrid"), PEOPLE)
        self.assertEqual(r3.relations, [])

    def test_clause_stage_can_be_switched_off(self):
        t = "After you clean the dataset, write a report."
        r = refine(t, ents(t, ("TASK", "write a report")), RefineConfig(span_snap=True), PEOPLE)
        self.assertEqual((r.relations, r.hints), ([], []))


class RecoveryTests(unittest.TestCase):
    def test_missing_action_phrase_and_assignee_are_recovered_and_labelled(self):
        t = "Anushree, can you clean the dataset by Thursday?"
        r = refine(t, ents(t, ("TASK", "can"), ("TEMPORAL", "by"), ("TEMPORAL", "Thursday")), from_preset("hybrid"), PEOPLE)
        got = {(e["type"], e["text"]): e["origin"] for e in r.entities}
        self.assertEqual(got, {("PERSON", "Anushree"): "rule", ("TASK", "clean the dataset"): "rule", ("TEMPORAL", "by Thursday"): "refined"})
        self.assertEqual(r.raw_entities[0]["text"], "can")                                  # the raw neural output is preserved
        self.assertTrue(r.imperative_ids == [] or all(i.startswith("rule-k") for i in r.imperative_ids))

    def test_dangling_and_fragmented_neural_spans_are_completed(self):
        t = "Bianca, please train the model by Friday."
        r = refine(t, ents(t, ("PERSON", "Bianca"), ("TASK", "please train the"), ("TEMPORAL", "by Friday")), from_preset("hybrid"), PEOPLE)
        self.assertEqual(texts(r.entities, "TASK"), ["please train the model"])
        t2 = "Anushree, could you update the budget spreadsheet by Friday?"
        r2 = refine(t2, ents(t2, ("TASK", "update the"), ("TASK", "spreadsheet")), from_preset("hybrid"), PEOPLE)
        self.assertEqual(texts(r2.entities, "TASK"), ["update the budget spreadsheet"])

    def test_a_complete_neural_span_is_not_overridden(self):
        t = "Bianca, please prepare the report by Friday."
        r = refine(t, ents(t, ("PERSON", "Bianca"), ("TASK", "please prepare the report"), ("TEMPORAL", "by Friday")), from_preset("hybrid"), PEOPLE)
        task = next(e for e in r.entities if e["type"] == "TASK")
        self.assertEqual((task["text"], task["origin"]), ("please prepare the report", "neural"))

    def test_no_action_phrase_is_invented_for_statements(self):
        for t in ("The server went down yesterday.", "Great job on the launch, everyone!", "Thanks for sending the invoice.", "Sure, I'll take care of it."):
            r = refine(t, [], from_preset("hybrid"), PEOPLE)
            self.assertEqual(texts(r.entities, "TASK"), [], t)

    def test_imperative_mood_is_recorded_for_the_reconciler(self):
        t = "After you clean the dataset, write a report."
        r = refine(t, ents(t, ("TASK", "write a report")), from_preset("hybrid"), PEOPLE)
        task = next(e for e in r.entities if e["text"] == "write a report")
        self.assertIn(task["id"], r.imperative_ids)
        t2 = "I'll send the invoice tomorrow."
        r2 = refine(t2, [], from_preset("hybrid"), PEOPLE)
        self.assertEqual(r2.imperative_ids, [])              # a first-person promise is already a request cue; not marked imperative

    def test_grammar_recovery_off_keeps_neural_fragments(self):
        t = "Bianca, please train the model by Friday."
        r = refine(t, ents(t, ("PERSON", "Bianca"), ("TASK", "please train the")), RefineConfig(span_snap=True), PEOPLE)
        self.assertEqual(texts(r.entities, "TASK"), ["please train the"])


class RelationScopingTests(unittest.TestCase):
    def rel(self, task, person):
        return {"source_id": task, "target_id": person, "label": "ASSIGNED_TO", "score": 0.97, "provenance": "neural"}

    def test_owner_across_a_clause_boundary_is_dropped_when_a_closer_one_exists(self):
        t = "Bianca, train the model, then Anushree should evaluate it."
        es = [{"id": "p1", "type": "PERSON", "start": 0, "end": 6, "text": "Bianca"}, {"id": "k1", "type": "TASK", "start": 8, "end": 23, "text": "train the model"},
              {"id": "p2", "type": "PERSON", "start": 30, "end": 38, "text": "Anushree"}, {"id": "k2", "type": "TASK", "start": 39, "end": 56, "text": "should evaluate it"}]
        rels = [self.rel("k1", "p1"), self.rel("k1", "p2"), self.rel("k2", "p1"), self.rel("k2", "p2")]
        out, edits = refine_relations(t, es, rels)
        self.assertEqual(sorted((r["source_id"], r["target_id"]) for r in out), [("k1", "p1"), ("k2", "p2")])
        self.assertEqual(len(edits), 2)

    def test_a_single_owner_is_never_dropped_even_across_a_clause(self):
        t = "Anushree, after you clean the dataset, please write a report."
        es = [{"id": "p", "type": "PERSON", "start": 0, "end": 8, "text": "Anushree"}, {"id": "k", "type": "TASK", "start": 40, "end": 61, "text": "please write a report"}]
        out, edits = refine_relations(t, es, [self.rel("k", "p")])
        self.assertEqual((len(out), edits), (1, []))

    def test_vocative_owner_is_recovered_by_rule(self):
        t = "Bianca, please book the room."
        es = [{"id": "p", "type": "PERSON", "start": 0, "end": 6, "text": "Bianca"}, {"id": "k", "type": "TASK", "start": 8, "end": 28, "text": "please book the room"}]
        out, edits = refine_relations(t, es, [])
        self.assertEqual([(r["label"], r["provenance"], r["rule"]) for r in out], [("ASSIGNED_TO", "rule", "vocative_or_subject_before_task")])

    def test_no_owner_is_recovered_across_a_sentence_or_clause_boundary(self):
        for t, pa in (("Bianca is away. Please book the room.", 6), ("Bianca, once it ships, book the room.", 6)):
            k = t.index("book") if "once" in t else t.index("Please")
            es = [{"id": "p", "type": "PERSON", "start": 0, "end": pa, "text": "Bianca"}, {"id": "k", "type": "TASK", "start": k, "end": len(t) - 1, "text": t[k:-1]}]
            self.assertEqual(refine_relations(t, es, [])[0], [], t)


if __name__ == "__main__":
    unittest.main()
