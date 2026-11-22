import unittest

from src.reconciliation.cues import classify_sentence, split_sentences


def op(text, **kw):
    return classify_sentence(text, **kw).op


class SentenceSplitTests(unittest.TestCase):
    def test_offsets_roundtrip(self):
        text = "Could we move it to Monday? Bianca, prepare the report by Friday.\nThanks!"
        ss = split_sentences(text)
        self.assertEqual([s.text for s in ss], ["Could we move it to Monday?", "Bianca, prepare the report by Friday.", "Thanks!"])
        for s in ss:
            self.assertEqual(text[s.start:s.end], s.text)

    def test_abbreviations_do_not_split(self):
        ss = split_sentences("Meet Mr. Lee at 3 p.m. on Nov. 15. Bring the draft.")
        self.assertEqual(len(ss), 2)
        self.assertTrue(ss[0].text.endswith("Nov. 15."))

    def test_no_terminal_punctuation(self):
        self.assertEqual([s.text for s in split_sentences("Monday works")], ["Monday works"])
        self.assertEqual(split_sentences("   "), [])


class IntentTests(unittest.TestCase):
    def test_completion(self):
        for t in ["I've finished the report.", "I have sent the notes", "The report is done.", "Done.", "All done", "The draft was submitted"]:
            self.assertEqual(op(t), "COMPLETE_TASK", t)

    def test_completion_gates(self):
        self.assertEqual(op("Did you finish the report?"), "NO_ACTION")
        self.assertEqual(op("I haven't finished the report."), "NO_ACTION")
        # "not done yet" is REOPEN; the reconciler turns it into NO_ACTION unless the referent is already completed
        self.assertEqual(op("The report is not done yet."), "REOPEN")
        self.assertEqual(op("Once I've finished the report, I'll send it."), "NO_ACTION")
        self.assertEqual(op("Is the report done?"), "NO_ACTION")

    def test_conditional_main_clause_still_counts(self):
        self.assertEqual(op("After lunch, I've finished the report."), "COMPLETE_TASK")

    def test_cancel_and_gates(self):
        self.assertEqual(op("Please cancel the review meeting."), "CANCEL_TASK")
        self.assertEqual(op("We no longer need the report."), "CANCEL_TASK")
        self.assertEqual(op("Never mind, scrap that."), "CANCEL_TASK")
        self.assertEqual(op("Should we cancel it?"), "NO_ACTION")
        self.assertEqual(op("If we cancel the review, we save time."), "NO_ACTION")
        self.assertEqual(op("Please don't cancel it."), "NO_ACTION")

    def test_reschedule_needs_a_date_expression(self):
        h = classify_sentence("Could we move it to Monday?", n_temporal=1)
        self.assertEqual((h.op, h.tentative), ("DATE_CHANGE", True))
        h = classify_sentence("The deadline is now Monday.", n_temporal=1)
        self.assertEqual((h.op, h.tentative), ("DATE_CHANGE", False))
        h = classify_sentence("I've moved the meeting to Tuesday.", n_temporal=1)
        self.assertEqual((h.op, h.extras["field_hint"]), ("DATE_CHANGE", "scheduled"))
        self.assertEqual(classify_sentence("Could we move it?", n_temporal=0).op, "NO_ACTION")
        h = classify_sentence("How about Tuesday?", n_temporal=1)
        self.assertEqual((h.op, h.tentative), ("DATE_CHANGE", True))

    def test_confirm_and_decline(self):
        for t in ["Monday works.", "Sounds good.", "Ok", "Sure, that works for me", "Agreed"]:
            self.assertEqual(op(t), "CONFIRM", t)
        for t in ["Monday doesn't work.", "No, can't do Monday."]:
            self.assertEqual(op(t), "DECLINE", t)
        self.assertNotEqual(op("Does Monday work?"), "CONFIRM")

    def test_reassign(self):
        self.assertEqual(op("Can you take this over?"), "UPDATE_ASSIGNEE")
        self.assertEqual(op("Dev will handle it instead."), "UPDATE_ASSIGNEE")
        self.assertEqual(op("I'll take this over."), "UPDATE_ASSIGNEE")

    def test_status(self):
        h = classify_sentence("I'm working on it.")
        self.assertEqual((h.op, h.extras["new_status"]), ("UPDATE_STATUS", "in_progress"))
        self.assertEqual(op("Are you working on it?"), "NO_ACTION")

    def test_dependency_and_reopen(self):
        h = classify_sentence("The release is waiting on the security review.")
        self.assertEqual((h.op, h.extras["right"]), ("ADD_DEPENDENCY", "the security review"))
        self.assertEqual(op("Actually the report is not done yet."), "REOPEN")

    def test_create_requires_evidence(self):
        kw = dict(has_task_candidate=True)
        self.assertEqual(op("Bianca, prepare the report by Friday.", candidate_has_due=True, candidate_assignee_resolved=True, **kw), "CREATE_TASK")
        self.assertEqual(op("Please send the notes.", **kw), "CREATE_TASK")
        self.assertEqual(op("I'll send the notes.", **kw), "CREATE_TASK")
        self.assertEqual(op("Could you send the notes by Friday?", candidate_has_due=True, **kw), "CREATE_TASK")

    def test_create_blocked_for_history_questions_and_bare_phrases(self):
        kw = dict(has_task_candidate=True)
        self.assertEqual(op("The API failed yesterday.", **kw), "NO_ACTION")
        self.assertEqual(op("The API failed yesterday.", candidate_assignee_resolved=True, **kw), "NO_ACTION")
        self.assertEqual(op("Who sent the notes?", **kw), "NO_ACTION")
        self.assertEqual(op("The meeting notes.", **kw), "NO_ACTION")
        self.assertEqual(classify_sentence("The API failed yesterday.", **kw).reason, "historical statement (no instruction)")

    def test_nothing_actionable(self):
        self.assertEqual(op("Thanks!"), "NO_ACTION")
        self.assertEqual(op("Hope you are well."), "NO_ACTION")

    def test_formal_email_false_positives_stay_quiet(self):
        # found by reading corpus-replay samples
        self.assertEqual(op("Please let me know when this is complete."), "NO_ACTION")
        self.assertEqual(op("Let me know once the report is done."), "NO_ACTION")
        self.assertEqual(classify_sentence("The meeting will be held on Monday at 3 pm.", n_temporal=1).op, "NO_ACTION")
        self.assertEqual(classify_sentence("He'd add much needed depth to night shift until Friday.", n_temporal=1).op, "NO_ACTION")
        self.assertEqual(classify_sentence("The deal ticket shows that I changed the deal at 8:50 am.", n_temporal=1).op, "NO_ACTION")
        self.assertEqual(classify_sentence("The meeting is now Friday at 3.", n_temporal=1).op, "DATE_CHANGE")
        self.assertEqual(classify_sentence("The new deadline is Friday.", n_temporal=1).op, "DATE_CHANGE")

    def test_ready_completion_cue_positive_and_negative(self):
        for t in ["The dataset is ready.", "The migration script is ready for review.", "The report was ready.", "It is ready.", "The data has been ready since noon."]:
            self.assertEqual(op(t), "COMPLETE_TASK", t)
        for t in ["We are ready to start.", "I am ready.", "They are ready.", "Are you ready?", "Is the report ready?", "Tell me when it is ready.",
                  "Once the build is ready, deploy it.", "The build is not ready.", "Ready for settlements draft."]:
            self.assertNotEqual(op(t), "COMPLETE_TASK", t)

    def test_future_start_cue_positive_and_negative(self):
        for t, temporals in [("I'll begin training now.", ["now"]), ("I will start on the report.", []), ("We'll kick off the migration now.", ["now"]),
                             ("I'm going to start training.", [])]:
            h = classify_sentence(t, temporal_texts=temporals)
            self.assertEqual((h.op, h.extras.get("new_status")), ("UPDATE_STATUS", "in_progress"), t)
        for t, temporals in [("I'll start training tomorrow.", ["tomorrow"]), ("I'll begin on Monday.", ["Monday"]), ("If you approve, I'll start training.", []),
                             ("Should I start now?", ["now"]), ("When it is ready I'll start.", [])]:
            self.assertNotEqual(classify_sentence(t, temporal_texts=temporals).op, "UPDATE_STATUS", t)


if __name__ == "__main__":
    unittest.main()
