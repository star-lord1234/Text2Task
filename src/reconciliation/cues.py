"""Sentence splitting and rule-based intent cues for reconciliation (Phase 5, cue set cues-v1).

Intent is decided per sentence. The detector is conservative: negation, questions, conditionals and
historical statements are gated out, and when two intents compete the first in PRIORITY wins. A
sentence that carries an operation intent but fails a gate becomes NO_ACTION with a reason.
These rules are brittle by design (they will miss paraphrases); a miss yields NO_ACTION or a
flagged proposal, never a silent state change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

CUE_SET_VERSION = "cues-v1"

# --------------------------------------------------------------------------- sentences
_ABBREV = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "inc", "ltd", "co", "no", "st", "e.g", "i.e", "a.m", "p.m",
           "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "mon", "tue", "tues", "wed", "thu",
           "thur", "thurs", "fri", "sat", "sun", "approx", "dept", "fig"}


@dataclass
class Sentence:
    index: int
    start: int
    end: int
    text: str


def split_sentences(text: str) -> list[Sentence]:
    """Split with character offsets. Newlines and . ! ? followed by space+capital/digit end a sentence."""
    spans: list[tuple[int, int]] = []
    start = 0
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        boundary = False
        if ch == "\n":
            boundary = True
        elif ch in ".!?":
            j = i
            while j + 1 < n and text[j + 1] in ".!?\"')":
                j += 1
            k = j + 1
            if k >= n:
                boundary, i = True, j
            elif text[k].isspace():
                m = k
                while m < n and text[m] in " \t":
                    m += 1
                nxt = text[m] if m < n else ""
                word = re.search(r"([A-Za-z.]+)$", text[start:i])
                prev = word.group(1).lower().rstrip(".") if word else ""
                is_abbrev = ch == "." and (prev in _ABBREV or (len(prev) == 1 and prev.isalpha()))
                if ch == "." and nxt and nxt.islower():
                    is_abbrev = True
                if not is_abbrev and (nxt == "" or nxt.isupper() or nxt.isdigit() or nxt in "\"'(" or ch in "!?"):
                    boundary, i = True, j
        if boundary:
            spans.append((start, i + 1))
            start = i + 1
        i += 1
    if start < n:
        spans.append((start, n))
    out = []
    for s, e in spans:
        raw = text[s:e]
        stripped = raw.strip()
        if not stripped:
            continue
        lead = len(raw) - len(raw.lstrip())
        out.append(Sentence(len(out), s + lead, s + lead + len(stripped), stripped))
    return out


# --------------------------------------------------------------------------- cue patterns
def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


QUESTION_START = _rx(r"^(?:did|have|has|had|is|are|was|were|do|does|when|what|who|where|why|how|any update|any news)\b")
NEGATION = _rx(r"\b(?:not|never|no|\w*n't|cannot|yet to|unable to|without)\b")
CONDITIONAL_START = _rx(r"^(?:if|once|when|unless|after|before|as soon as|until|assuming)\b")
HISTORICAL = _rx(r"\b(?:yesterday|last (?:week|month|year|night|time)|earlier|ago|previously|failed|broke|crashed|was|were|had|did)\b")
REQUEST_CUE = _rx(r"\b(?:please|kindly|could you|can you|would you|will you|need to|needs to|needed to|should|must|have to|has to|make sure|"
                  r"don't forget|do not forget|remember to|let's|let us|let me|i'll|i will|i can|i'm going to|i am going to|we'll|we will|"
                  r"going to|i'd like you to|i need you to|i want you to|action item|to-?do|"
                  r"(?:can|could|would) (?:someone|anyone|somebody|anybody)|does (?:anyone|anybody)|is (?:anyone|anybody) able)\b")

COMPLETE_FIRST = _rx(r"\bi(?:'ve| have|'m| am)?\s+(?:just\s+|now\s+|already\s+|finally\s+|all\s+)?"
                     r"(?:finished|completed|done|sent|submitted|filed|delivered|wrapped up|handled|updated|fixed|uploaded|booked|"
                     r"reviewed|approved|signed|shared|published|posted|resolved|closed)\b")
COMPLETE_PASSIVE = _rx(r"\b(?:is|are|was|has been|have been|got|now)\s+(?:now\s+|already\s+|all\s+)?"
                       r"(?:done|complete|completed|finished|sent|submitted|filed|delivered|taken care of|sorted|handled|resolved)\b")
COMPLETE_PLAIN = _rx(r"^(?:all\s+)?(?:done|finished|completed)\b|\bthat'?s (?:done|finished|complete)\b|\ball done\b")
# "<noun phrase> is ready": completion of a deliverable. Pronoun subjects ("we are ready", "I am ready") and "ready to ..." are not.
COMPLETE_READY = _rx(r"\b(\w+)\s+(?:is|are|was|has been|have been|got)\s+(?:now\s+|already\s+|all\s+)?ready\b(?!\s+to\b)")
READY_PRONOUN_SUBJECTS = {"i", "we", "you", "they", "he", "she", "who", "everyone", "everybody", "all", "both", "guys", "team"}
# future-tense start ("I'll begin training now"): in progress only when the start is not deferred to another time
FUTURE_START = _rx(r"\b(?:i(?:'ll| will)|i(?:'m| am) going to|we(?:'ll| will)|let me)\s+(?:now\s+|just\s+|then\s+)?(?:begin|start|kick off|get started)\b")
NOW_WORDS = {"now", "right now", "today", "right away", "immediately", "straight away", "at once", "asap"}
CANCEL = _rx(r"\b(?:cancel(?:l?ed|ing|s)?|call(?:ed)? off|scrap(?:ped)?|no longer (?:need(?:ed)?|necessary|required|relevant)|"
             r"(?:don't|do not|doesn't|does not) need to|not needed anymore|drop(?:ped)? (?:it|this|that)|forget (?:about )?(?:it|this|that)|"
             r"never ?mind|abandon\w*)\b")
STATUS_PROGRESS = _rx(r"\b(?:i(?:'m| am)|we(?:'re| are))\s+(?:currently\s+|now\s+|already\s+)?(?:working on|on it|looking into|starting|handling|busy with)\b"
                      r"|\b(?:started|begun|starting)\s+(?:on|working)\b|\bon it\b|\bworking on it\b")
REASSIGN = _rx(r"\b(?:(?:can|could|would) you (?:please )?(?:take (?:this|it) over|take over|handle (?:this|it)|take care of (?:this|it)|pick (?:this|it) up)|"
               r"reassign\w*|hand(?:ing)? (?:this|it) (?:over )?to|handing over|"
               r"(?:will|can|should|shall) (?:take (?:this|it) over|take over|handle (?:this|it)|do (?:this|it))(?: instead)?|"
               r"i(?:'ll| will| can) take (?:this|it)(?: over)?|instead of)\b")
RESCHEDULE_VERB = _rx(r"\b(?:move|moved|moving|push(?:ed)?|pushing|postpone[d]?|reschedul\w+|delay(?:ed)?|bump(?:ed)?)\b")
RESCHEDULE_DECL = _rx(r"\b(?:deadline|due date|due|meeting|call|review|demo)\b.{0,25}\b(?:is now|will now be|now is|has (?:been )?changed|changed to|is changed to)\b|\bnow due\b|\b(?:new|revised|updated) (?:deadline|due date|date|time)\b")
RESCHEDULE_ASK = _rx(r"^(?:how|what) about\b|\bwould .{1,30} work\b|\bis .{1,25} (?:ok(?:ay)?|possible)\b|\b(?:is|would be) better\b|\bprefer\b|\brather\b")
CONFIRM_PHRASE = _rx(r"\b(?:works for (?:me|us)|that works|sounds (?:good|fine|great)|is fine|is good|is ok(?:ay)?|good with me|fine (?:with|by) me|"
                     r"agreed|i agree|confirmed?|no problem|will do)\b")
CONFIRM_SHORT = _rx(r"^(?:ok(?:ay)?|sure|yes|yep|yeah|fine|great|perfect|works|good|agreed|deal)\b")
DECLINE = _rx(r"\b(?:doesn't|does not|won't|will not|can't|cannot|isn't|is not) (?:work|possible|ok(?:ay)?|good)\b|\bcan't do\b|\bnot possible\b|^no\b[,.!]?")
DEPENDENCY = _rx(r"\b(?:is |are )?(?:waiting (?:on|for)|depends? on|dependent on|blocked (?:by|on))\b")
REOPEN = _rx(r"\b(?:re-?open\w*|not (?:actually |really )?(?:done|finished|complete)(?: after all| yet)?|still (?:needs?|not (?:done|finished)))\b")

SCHED_WORDS = _rx(r"\b(?:meeting|call|session|demo|interview|presentation|appointment|stand-?up|workshop|conference|lunch|dinner)\b")
DUE_WORDS = _rx(r"\b(?:deadline|due|by)\b")
ANAPHORA = _rx(r"\b(?:it|this|that|the task|the above|them)\b")
TASK_ID = _rx(r"(?:\bT-?(\d+)\b|#(\d+)\b)")


@dataclass
class IntentHit:
    op: str                     # COMPLETE_TASK CANCEL_TASK UPDATE_STATUS UPDATE_ASSIGNEE DATE_CHANGE CONFIRM DECLINE
                                # ADD_DEPENDENCY CREATE_TASK REOPEN NO_ACTION
    cue: Optional[str] = None
    cue_span: Optional[tuple[int, int]] = None      # offsets inside the sentence
    tentative: bool = False
    question: bool = False
    reason: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


def is_question(text: str) -> bool:
    t = text.strip()
    return t.endswith("?") or bool(QUESTION_START.match(t))


def _negated(sentence: str, cue_start: int) -> bool:
    window = sentence[max(0, cue_start - 28):cue_start]
    return bool(NEGATION.search(window))


SUBORDINATOR = _rx(r"\b(?:when|whenever|once|if|unless|until|as soon as|after|before|assuming|so that)\b")


def _gated(sentence: str, m: re.Match, *, allow_question: bool, question: bool) -> Optional[str]:
    if question and not allow_question:
        return "question"
    if _negated(sentence, m.start()):
        return "negated"
    clause_start = max(sentence.rfind(",", 0, m.start()), sentence.rfind(";", 0, m.start()), sentence.rfind(":", 0, m.start()))
    clause_before = sentence[clause_start + 1:m.start()]
    if SUBORDINATOR.search(clause_before):         # the cue sits in a when/if/once/after... clause: not a report
        return "conditional"
    return None


def classify_sentence(text: str, *, has_task_candidate: bool = False, candidate_has_due: bool = False,
                      candidate_assignee_resolved: bool = False, n_temporal: int = 0, temporal_texts: Sequence[str] = (),
                      imperative_candidate: bool = False) -> IntentHit:
    """Return the single highest-priority intent for one sentence."""
    s = text.strip()
    q = is_question(s)
    blocked: list[str] = []

    def hit(op, m, **kw):
        return IntentHit(op=op, cue=m.group(0), cue_span=(m.start(), m.end()), question=q, **kw)

    # REOPEN (flag only)
    m = REOPEN.search(s)
    if m and not q:
        return hit("REOPEN", m)

    # CANCEL
    m = CANCEL.search(s)
    if m:
        why = _gated(s, m, allow_question=False, question=q)
        if why is None and not re.search(r"\b(?:should|shall|could|can|would|do) we\b", s, re.I):
            return hit("CANCEL_TASK", m)
        blocked.append(f"cancel:{why or 'tentative'}")

    # COMPLETE
    for rx, name in ((COMPLETE_FIRST, "first_person"), (COMPLETE_PASSIVE, "passive"), (COMPLETE_PLAIN, "plain")):
        m = rx.search(s)
        if m:
            why = _gated(s, m, allow_question=False, question=q)
            if why is None:
                return hit("COMPLETE_TASK", m, extras={"form": name})
            blocked.append(f"complete:{why}")
            break

    m = COMPLETE_READY.search(s)
    if m and m.group(1).lower() not in READY_PRONOUN_SUBJECTS:
        why = _gated(s, m, allow_question=False, question=q)
        if why is None:
            h = hit("COMPLETE_TASK", m, extras={"form": "ready"})
            h.cue_span = (m.end(1), m.end())            # keep the subject noun ("script") available for referent matching
            return h
        blocked.append(f"complete:{why}")

    # REASSIGN (requests allowed)
    m = REASSIGN.search(s)
    if m:
        why = _gated(s, m, allow_question=True, question=q)
        if why is None:
            return hit("UPDATE_ASSIGNEE", m, tentative=q)
        blocked.append(f"reassign:{why}")

    # RESCHEDULE (needs a date expression in the sentence; checked by the reconciler via entities)
    m = RESCHEDULE_VERB.search(s) or RESCHEDULE_DECL.search(s)
    ask = RESCHEDULE_ASK.search(s)
    if (m or ask) and n_temporal > 0:
        mm = m or ask
        why = _gated(s, mm, allow_question=True, question=q)
        if why is None:
            tentative = bool(q or ask or re.search(r"\b(?:could|can|would|should|maybe|perhaps|might|how about|what if)\b", s, re.I))
            fld = "scheduled" if SCHED_WORDS.search(s) and not DUE_WORDS.search(s) else ("due" if DUE_WORDS.search(s) else None)
            return hit("DATE_CHANGE", mm, tentative=tentative, extras={"field_hint": fld})
        blocked.append(f"reschedule:{why}")

    # DECLINE / CONFIRM (short replies to a pending proposal)
    words = len(re.findall(r"\w+", s))
    m = DECLINE.search(s)
    if m and words <= 8 and not q:
        return hit("DECLINE", m)
    m = CONFIRM_PHRASE.search(s)
    if m and words <= 12 and not q and not _negated(s, m.start()):
        return hit("CONFIRM", m)
    m = CONFIRM_SHORT.match(s)
    if m and words <= 5 and not q:
        return hit("CONFIRM", m)
    m = re.search(r"\bworks\b", s, re.I)
    if m and words <= 6 and not q and not _negated(s, m.start()):
        return hit("CONFIRM", m)

    # STATUS
    m = FUTURE_START.search(s)
    if m:
        why = _gated(s, m, allow_question=False, question=q)
        if why is None and CONDITIONAL_START.match(s):
            why = "conditional"                       # "If you approve, I'll start": a promise, not a start
        later = [t for t in temporal_texts if t.strip().lower() not in NOW_WORDS]
        if why is None and not later:
            return hit("UPDATE_STATUS", m, extras={"new_status": "in_progress"})
        blocked.append(f"status:{why or 'start deferred to ' + later[0]}")
    m = STATUS_PROGRESS.search(s)
    if m:
        why = _gated(s, m, allow_question=False, question=q)
        if why is None:
            return hit("UPDATE_STATUS", m, extras={"new_status": "in_progress"})
        blocked.append(f"status:{why}")

    # DEPENDENCY
    m = DEPENDENCY.search(s)
    if m and not q:
        return hit("ADD_DEPENDENCY", m, extras={"left": s[:m.start()].strip(" ,;:"), "right": s[m.end():].strip(" ,;:.")})

    # CREATE (requires a Phase 4 task candidate in the sentence)
    if has_task_candidate:
        request = REQUEST_CUE.search(s)
        if HISTORICAL.search(s) and not request and not candidate_has_due:
            return IntentHit(op="NO_ACTION", reason="historical statement (no instruction)", question=q)
        if request or candidate_has_due or candidate_assignee_resolved or imperative_candidate:
            if q and not request:
                return IntentHit(op="NO_ACTION", reason="question without a request", question=q)
            return IntentHit(op="CREATE_TASK", cue=request.group(0) if request else None,
                             cue_span=(request.start(), request.end()) if request else None, question=q,
                             tentative=q, extras={"evidence": "request_cue" if request else
                                                  "due_date" if candidate_has_due else "resolved_assignee" if candidate_assignee_resolved else "imperative_mood"})
        return IntentHit(op="NO_ACTION", reason="task-like phrase without request, owner or deadline", question=q)

    reason = "; ".join(blocked) if blocked else ("question" if q else "no actionable cue")
    return IntentHit(op="NO_ACTION", reason=reason, question=q)
