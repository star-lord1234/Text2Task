import json
import unittest
from pathlib import Path

from src.reconciliation.matcher import Matcher, content_tokens, lexical_score, stem
from src.reconciliation.models import Task
from src.reconciliation.store import TaskStore

CFG = json.loads((Path(__file__).resolve().parents[1] / "configs" / "phase5.json").read_text())
W = CFG["matching"]["weights"]
WS = "w"


def task(tid, title, owner="bianca", status="open", touched=1, src="m1", last="m1", aliases=()):
    return Task(task_id=tid, workspace_id=WS, thread_id="th", title=title, owner_id=owner, status=status, source_message_id=src,
                last_touched_message_id=last, last_touched_seq=touched, aliases=list(aliases))


def run(tasks, sentence, *, speaker="bianca", seq=2, op="COMPLETE_TASK", reply=None, matcher=None, spans=()):
    store = TaskStore()
    toks = content_tokens(sentence, spans)
    return (matcher or Matcher(CFG)).match(store, WS, tasks, sentence=sentence, tokens=toks, speaker_id=speaker, in_reply_to=reply,
                                           current_seq=seq, op=op)


class TokenTests(unittest.TestCase):
    def test_tokens_drop_stopwords_filler_and_spans(self):
        self.assertEqual(content_tokens("I've finished the report."), ["report"])
        self.assertEqual(content_tokens("prepare the report by Friday", [(22, 28)]), ["prepare", "report"])
        self.assertEqual(content_tokens("Could we move it to Monday?", [(20, 26)]), [])
        self.assertEqual(stem("reports"), "report")
        self.assertEqual(stem("review"), "review")

    def test_lexical_score_shapes(self):
        self.assertAlmostEqual(lexical_score(["prepare", "report"], ["prepare", "report"], W), 50)
        self.assertEqual(lexical_score(["report"], ["prepare", "report"], W), 40)
        self.assertEqual(lexical_score(["x"], ["prepare", "report"], W), 0)
        self.assertLess(lexical_score(["prepare", "report"], ["review", "report"], W), 20)


class MatcherTests(unittest.TestCase):
    def test_object_match_with_owner_is_matched(self):
        r = run([task("T-1", "prepare the report"), task("T-2", "book the room", owner="riya")], "I've finished the report.")
        self.assertEqual((r.outcome, r.task_id), ("MATCHED", "T-1"))
        self.assertIn("owner_is_speaker", r.ranked[0]["signals"])

    def test_two_tasks_same_object_is_ambiguous_not_guessed(self):
        r = run([task("T-1", "prepare the report"), task("T-2", "review the report")], "I've finished the report.")
        self.assertEqual(r.outcome, "AMBIGUOUS_REFERENT")
        self.assertIsNone(r.task_id)
        self.assertEqual({x["task_id"] for x in r.ranked}, {"T-1", "T-2"})

    def test_explicit_id_is_decisive(self):
        r = run([task("T-1", "prepare the report"), task("T-2", "review the report")], "T-2 is done", op="COMPLETE_TASK")
        self.assertEqual((r.outcome, r.task_id), ("MATCHED", "T-2"))

    def test_reply_to_breaks_a_lexical_tie(self):
        ts = [task("T-1", "prepare the report", src="m1", last="m1", touched=1), task("T-2", "review the report", src="m5", last="m5", touched=1)]
        r = run(ts, "I've finished the report.", reply="m1")
        self.assertEqual((r.outcome, r.task_id), ("MATCHED", "T-1"))

    def test_anaphora_unique_recent_task(self):
        r = run([task("T-1", "prepare the report", touched=1)], "Could we move it to Monday?", op="DATE_CHANGE", spans=[(20, 26)])
        self.assertEqual((r.outcome, r.task_id), ("MATCHED", "T-1"))
        self.assertIn("anaphora", r.ranked[0]["signals"])

    def test_anaphora_two_recent_tasks_is_ambiguous(self):
        r = run([task("T-1", "prepare the report", touched=1), task("T-2", "book the room", touched=1)], "Could we move it to Monday?",
                op="DATE_CHANGE", spans=[(20, 26)])
        self.assertEqual(r.outcome, "AMBIGUOUS_REFERENT")

    def test_anaphora_outside_window_is_no_referent(self):
        r = run([task("T-1", "prepare the report", touched=1)], "Could we move it to Monday?", op="DATE_CHANGE", seq=9, spans=[(20, 26)])
        self.assertEqual(r.outcome, "NO_REFERENT")

    def test_bare_done_is_anaphoric(self):
        r = run([task("T-1", "prepare the report", touched=1)], "Done.")
        self.assertEqual((r.outcome, r.task_id), ("MATCHED", "T-1"))

    def test_no_overlap_is_no_referent(self):
        r = run([task("T-1", "prepare the report")], "I've sent the invoice.")
        self.assertEqual(r.outcome, "NO_REFERENT")
        self.assertEqual(run([], "I've sent the invoice.").outcome, "NO_REFERENT")

    def test_active_task_beats_closed_duplicate(self):
        r = run([task("T-1", "prepare the report", status="completed"), task("T-2", "prepare the report")], "Can you prepare the report?", op="DATE_CHANGE")
        self.assertEqual((r.outcome, r.task_id), ("MATCHED", "T-2"))

    def test_embeddings_only_support(self):
        m = Matcher({**CFG, "matching": {**CFG["matching"], "use_embeddings": True}}, embedder=lambda a, b: 1.0)
        r = run([task("T-1", "book the room")], "I've finished the invoice.", matcher=m)
        self.assertEqual(r.outcome, "NO_REFERENT")   # similarity alone (max +10) cannot reach the low threshold


if __name__ == "__main__":
    unittest.main()
