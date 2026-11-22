"""Referent matching (Phase 5): which existing task does a sentence refer to?

Transparent additive score; every signal's contribution is returned so a reviewer can see why a task
matched. Outcomes: MATCHED (score >= high and margin over the runner-up), AMBIGUOUS_REFERENT
(plausible but not decisive, including a single weak candidate), NO_REFERENT. Optional embeddings
may add a small supporting score, are off by default, and never create a match on their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from src.reconciliation.cues import ANAPHORA, TASK_ID
from src.reconciliation.models import Task
from src.reconciliation.store import TaskStore

STOPWORDS = set("""a an the to of for in on at by with from and or but if then so as is are was were be been being am do does did have has had
i you he she it we they me my your our their him her them us this that these those there here not no yes ok okay sure please kindly
could would should can will shall may might must just now also still already really very too up out about into over after before again
what when who whom which why how any some all both each more most other such than only own same s t get got let lets let's thanks
thank hi hello hey dear regards best actually really indeed honestly basically anyway yet task tasks item items thing things anymore""".split())
FILLER_VERBS = set("""move moved moving push pushed postpone postponed reschedule rescheduled delay delayed shift bump extend extended change
changed finish finished complete completed done ready available arrive arrives sent submitted cancel cancelled canceled working work works look looking start started
take took handle handled reassign instead over need needs needed want make sure""".split())


def stem(tok: str) -> str:
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3 and not tok.endswith("ss"):
            return tok[: len(tok) - len(suf)] + rep
    return tok


FILLER_STEMS = {stem(w) for w in FILLER_VERBS}


def content_tokens(text: str, remove_spans: Sequence[tuple[int, int]] = (), drop_filler: bool = True) -> list[str]:
    chars = list(text)
    for s, e in remove_spans:
        for i in range(max(0, s), min(len(chars), e)):
            chars[i] = " "
    clean = "".join(chars).lower()
    clean = TASK_ID.sub(" ", clean)
    clean = re.sub(r"(?<=\w)'(?:ve|ll|re|d|s|m|t)\b", "", clean)     # i've -> i, don't -> don
    toks = re.findall(r"[a-z][a-z0-9]+", clean)
    out = []
    for t in toks:
        st = stem(t)
        if t in STOPWORDS or (drop_filler and (t in FILLER_VERBS or st in FILLER_STEMS)):
            continue
        out.append(st)
    return out


def lexical_score(a: Sequence[str], b: Sequence[str], w: Mapping[str, float]) -> float:
    A, B = set(a), set(b)
    shared = len(A & B)
    if not A or not B or shared == 0:
        return 0.0
    containment = shared / len(A)
    jacc = shared / len(A | B)
    if len(A) >= 2 and shared >= 2:
        score = w["lexical_full"] * max(jacc, 0.7 * containment)
        if containment == 1.0:                       # every content word of the phrase appears in the task title
            score = max(score, 0.9 * w["lexical_full"])
        return score
    if len(A) == 1:
        return float(w["lexical_single"])
    return w["lexical_weak"] * containment


@dataclass
class MatchResult:
    outcome: str                                  # MATCHED | AMBIGUOUS_REFERENT | NO_REFERENT
    task_id: Optional[str] = None
    ranked: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "task_id": self.task_id, "ranked": self.ranked, "reason": self.reason}


class Matcher:
    def __init__(self, config: Mapping[str, Any], embedder: Optional[Callable[[str, str], float]] = None):
        m = config["matching"]
        self.w, self.t = m["weights"], m["thresholds"]
        self.window = int(m["anaphora_window_messages"])
        self.closed_penalty = float(m["closed_task_penalty"])
        self.use_embeddings = bool(m.get("use_embeddings")) and embedder is not None
        self.embedder = embedder

    def match(self, store: TaskStore, ws: str, tasks: Sequence[Task], *, sentence: str, tokens: Sequence[str],
              speaker_id: Optional[str], in_reply_to: Optional[str], current_seq: int, op: str,
              allow_anaphora: bool = True) -> MatchResult:
        if not tasks:
            return MatchResult("NO_REFERENT", reason="no tasks in this thread")
        by_id = {t.task_id: t for t in tasks}
        signals: dict[str, dict[str, float]] = {t.task_id: {} for t in tasks}

        for m in TASK_ID.finditer(sentence):
            tid = f"T-{m.group(1) or m.group(2)}"
            if tid in signals:
                signals[tid]["explicit_id"] = self.w["explicit_id"]

        if in_reply_to:
            replied = {t.task_id for t in tasks if in_reply_to in (t.source_message_id, t.last_touched_message_id)}
            replied |= {p.task_id for p in store.list_proposals(ws, message_id=in_reply_to) if p.task_id in signals}
            for tid in replied:
                signals[tid]["reply_to"] = self.w["reply_to"]

        for t in tasks:
            titles = [t.title, *t.aliases]
            best = max((lexical_score(tokens, content_tokens(x, drop_filler=False), self.w) for x in titles), default=0.0)
            if best:
                signals[t.task_id]["lexical"] = best
            if self.use_embeddings:
                sim = max((self.embedder(sentence, x) for x in titles), default=0.0)
                if sim > 0:
                    signals[t.task_id]["embedding"] = self.w["embedding_max"] * min(sim, 1.0)

        anaphoric = allow_anaphora and (bool(ANAPHORA.search(sentence)) or not tokens)
        if anaphoric:
            active = [t for t in tasks if t.status in ("open", "in_progress")]
            pool = active or list(tasks)
            recent = [t for t in pool if t.last_touched_seq > 0 and current_seq - t.last_touched_seq < self.window]
            for t in recent:
                signals[t.task_id]["anaphora"] = self.w["anaphora_unique"] if len(recent) == 1 else self.w["anaphora_multi"]

        content = {"explicit_id", "reply_to", "lexical", "anaphora"}
        for t in tasks:
            sig = signals[t.task_id]
            if not (content & set(sig)):
                continue   # owner/recency/closed adjustments only refine tasks that already have content evidence
            if sig and op in ("COMPLETE_TASK", "UPDATE_STATUS") and speaker_id and t.owner_id == speaker_id:
                sig["owner_is_speaker"] = self.w["owner_is_speaker"]
            if sig and t.last_touched_seq > 0:
                sig["recency"] = self.w["recency_max"] / (1 + max(0, current_seq - t.last_touched_seq))
            if sig and t.status in ("completed", "cancelled"):
                sig["closed_task_penalty"] = -self.closed_penalty

        ranked = []
        for tid, sig in signals.items():
            if not sig:
                continue
            raw = sum(v for k, v in sig.items() if k != "closed_task_penalty")
            ranked.append({"task_id": tid, "score": round(sum(sig.values()), 2), "raw_score": round(raw, 2),
                           "signals": {k: round(v, 2) for k, v in sig.items()}})
        ranked.sort(key=lambda r: (-r["score"], r["task_id"]))
        # thresholds use the raw score (a lone closed task must still be identifiable so the transition can be flagged);
        # the closed-task penalty only affects ranking and the margin over the runner-up.
        if not ranked or ranked[0]["raw_score"] < self.t["low"]:
            return MatchResult("NO_REFERENT", ranked=ranked[:5], reason="no task scored above the low threshold")
        top = ranked[0]["score"]
        second = ranked[1]["score"] if len(ranked) > 1 else 0.0
        decisive_signal = any(k in ranked[0]["signals"] for k in ("explicit_id", "lexical", "anaphora", "reply_to"))
        if ranked[0]["raw_score"] >= self.t["high"] and top - second >= self.t["margin"] and decisive_signal:
            return MatchResult("MATCHED", ranked[0]["task_id"], ranked[:5], "decisive score and margin")
        close = [r for r in ranked if r["raw_score"] >= self.t["low"]]
        return MatchResult("AMBIGUOUS_REFERENT", None, close[:5],
                           "several plausible tasks" if len(close) > 1 else "single weak candidate")
