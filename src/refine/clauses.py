"""Step 5: clause-level dependency extraction directly from the raw sentence.

A sentence is matched against a small table of prerequisite constructions ('After A, B', 'B once A', 'Before A, B', 'A, then B', 'B until A').
Each side is resolved on its own: an existing TASK span, a recovered action phrase (a new task), or a *reference* (a state clause such as
'the dataset is cleaned', or a completion verb: 'Anushree finishes the dataset'), which the reconciler matches to an existing task. A side
that is neither (a time, an event, 'lunch', 'when you get a chance') produces no dependency. Output is data; nothing is applied here."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from src.refine.grammar import Phrase, find_action_phrases, has_verb, is_state_clause, lemma, tokenize
from src.refine.lexicon import AUX, CLAUSE_CUE, COMPLETION_VERBS, PRON
from src.refine.temporal import detect

SUB = r"(?:after|once|as soon as|when|whenever|following|upon)"
VOC = r"(?:[A-Za-z][A-Za-z'\-]*,\s+)?"                    # an optional leading vocative: "Anushree, after you ..."
BLOCKED = re.compile(r"\b(?:can't|cannot|can not|won't|will not|shouldn't|must not|isn't|aren't|not able to|unable to)\s+(?:\w+\s+)?(?:start|begin|proceed|move|go|continue|launch|ship|finish|complete|happen|run)\b|\bis blocked\b|\bhas to wait\b", re.I)


@dataclass
class Side:
    start: int
    end: int
    kind: str                       # "task" | "reference" | "none"
    phrase: Optional[Phrase] = None
    task_id: Optional[str] = None   # an existing TASK entity covering this side

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "kind": self.kind, "task_id": self.task_id, "phrase": self.phrase.text if self.phrase else None}


@dataclass
class ClauseDep:
    dependent: Side
    prerequisite: Side
    cue: str
    pattern: str
    sentence: str
    sentence_start: int

    def to_dict(self) -> dict[str, Any]:
        return {"dependent": self.dependent.to_dict(), "prerequisite": self.prerequisite.to_dict(), "cue": self.cue, "pattern": self.pattern, "evidence": self.sentence}


def _trim(text: str, a: int, b: int) -> tuple[int, int]:
    while a < b and text[a] in " \t,;:":
        a += 1
    while b > a and text[b - 1] in " \t,;:.!?":
        b -= 1
    return a, b


def _split_then(text: str, s: int, e: int) -> list[tuple[int, int]]:
    parts, last = [], s
    for m in re.finditer(r"\s*[,;]?\s*(?:and\s+)?then\s+", text[s:e], re.I):
        parts.append((last, s + m.start()))
        last = s + m.end()
    parts.append((last, e))
    return [_trim(text, a, b) for a, b in parts if b > a]


def _constructions(text: str, s: int, e: int) -> list[tuple[str, str, tuple[int, int], tuple[int, int]]]:
    """(pattern, cue, dependent_range, prerequisite_range) found in text[s:e]."""
    sent = text[s:e]
    out = []
    m = re.match(rf"\s*(?:first,?\s+)?(.+?)\s*[,;]?\s+(?:and\s+)?then\s+(.+)$", sent, re.I | re.S) if re.search(r"\bthen\b", sent, re.I) else None
    if m and not re.match(rf"\s*{VOC}{SUB}\b", sent, re.I):
        segs = _split_then(text, s + re.match(r"\s*(?:first,?\s+)?", sent, re.I).end(), e)
        for a, b in zip(segs, segs[1:]):
            out.append(("sequence", "then", b, a))                                  # later step depends on the earlier one
        return out
    m = re.match(rf"\s*{VOC}before\s+(.+?)\s*,\s*(.+)$", sent, re.I | re.S)
    if m:
        a = _trim(text, s + m.start(1), s + m.end(1)); b = _trim(text, s + m.start(2), s + m.end(2))
        return [("before_first", "before", a, b)]                                 # 'Before A, B': A waits for B
    m = re.match(rf"\s*{VOC}({SUB})\s+(.+?)\s*,\s*(?:then\s+)?(.+)$", sent, re.I | re.S)
    if m:
        a = _trim(text, s + m.start(2), s + m.end(2)); b = _trim(text, s + m.start(3), s + m.end(3))
        return [("cue_first", m.group(1).lower(), b, a)]                          # 'After A, B': B waits for A
    m = re.search(rf"^(.+?)\s*,?\s+(?:but\s+)?(?:only\s+)?({SUB}|until|till)\s+(.+)$", sent, re.I | re.S)
    if m:
        b = _trim(text, s + m.start(1), s + m.end(1)); a = _trim(text, s + m.start(3), s + m.end(3))
        return [("cue_after", m.group(2).lower(), b, a)]                         # 'B once/after/until A'
    m = re.search(r"^(.+?)\s+before\s+(.+)$", sent, re.I | re.S)
    if m:
        a = _trim(text, s + m.start(1), s + m.end(1)); b = _trim(text, s + m.start(2), s + m.end(2))
        return [("before_after", "before", b, a)]                                # 'A before B': B waits for A
    return out


def _side(text: str, rng: tuple[int, int], tasks: Sequence[dict[str, Any]], protected: Sequence[tuple[int, int]], names: Iterable[str], *, prerequisite: bool) -> Side:
    a, b = rng
    if b <= a:
        return Side(a, b, "none")
    clause = text[a:b]
    if BLOCKED.search(clause) and not prerequisite:
        return Side(a, b, "reference")                       # "Deployment can't start": a statement about existing work
    if prerequisite and is_state_clause(clause):
        return Side(a, b, "reference")                       # checked BEFORE neural spans: a neural fragment inside "the dataset is cleaned" is not a task
    phrases = find_action_phrases(text, a, b, protected=protected, names=names)
    if prerequisite and phrases and lemma(phrases[0].text.split()[0]) in COMPLETION_VERBS and phrases[0].evidence in ("after subject", "after modal"):
        return Side(a, b, "reference")                       # "Anushree finishes the dataset": progress on existing work
    covered = [t for t in tasks if t["start"] >= a and t["end"] <= b and has_verb(t["text"])]     # a verbless fragment is not a task
    if covered:
        return Side(a, b, "task", task_id=covered[0]["id"], phrase=phrases[0] if phrases else None)
    if not phrases:
        if prerequisite and _noun_phrase_only(clause):
            return Side(a, b, "reference")                   # "after the review": maybe an existing task; the reconciler decides, else nothing
        return Side(a, b, "none")
    return Side(a, b, "task", phrase=phrases[0])


def _noun_phrase_only(clause: str) -> bool:
    ws = [w.lower() for w in re.findall(r"[A-Za-z0-9']+", clause)]
    if not ws or len(ws) > 5:
        return False
    if any(w in PRON or w in AUX or w in CLAUSE_CUE for w in ws):
        return False                                         # a clause with a subject or verb ("you get a chance") is not a bare noun phrase
    return not _temporal_only(clause)


def _temporal_only(clause: str) -> bool:
    found = detect(clause)
    rest = clause
    for x in sorted(found, key=lambda x: -x["start"]):
        rest = rest[:x["start"]] + " " + rest[x["end"]:]
    return bool(found) and not re.search(r"[A-Za-z]{3,}", re.sub(r"\b(?:the|a|an|of|by|on|at|for|next|this)\b", "", rest, flags=re.I))


def extract_clause_dependencies(text: str, sentences: Sequence[Any], tasks: Sequence[dict[str, Any]], protected: Sequence[tuple[int, int]],
                                names: Iterable[str] = ()) -> list[ClauseDep]:
    deps: list[ClauseDep] = []
    for sent in sentences:
        for pat, cue, dep_rng, pre_rng in _constructions(text, sent.start, sent.end):
            dep = _side(text, dep_rng, tasks, protected, names, prerequisite=False)
            pre = _side(text, pre_rng, tasks, protected, names, prerequisite=True)
            if dep.kind == "none" or pre.kind == "none" or (dep.kind == "reference" and pre.kind != "reference"):
                continue                      # the dependent is a task (or a blocked reference); the prerequisite a task or a reference to existing work
            if dep.task_id and dep.task_id == pre.task_id:
                continue
            deps.append(ClauseDep(dep, pre, cue, pat, sent.text, sent.start))
    return deps
