"""Phase 7.5 step 6: lifecycle and acknowledgement cues that use EXISTING task context instead of a TASK span in the message.

Used only when the 'context_lifecycle' option is on and the base classifier found nothing actionable. Both cues are conservative:
a completion needs a participle/past form of the same verb as an open task plus at least one shared object word, and is gated by the same
question/negation/conditional checks as the base cues; an acknowledgement needs the speaker to own exactly one open task. The reconciler's
normal matcher still has to find a unique referent, otherwise the result is a flagged NO_ACTION, never a state change."""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence

from src.reconciliation.cues import IntentHit, _gated, is_question
from src.reconciliation.matcher import content_tokens, stem

PARTICIPLE = re.compile(r"\b(?:is|are|was|were|has been|have been|got|gets|now)\s+(?:now\s+|already\s+|all\s+|finally\s+|just\s+)?([a-z]+(?:ed|en))\b", re.I)
FIRST_PAST = re.compile(r"\bi(?:'ve| have)?\s+(?:just\s+|now\s+|already\s+|finally\s+)?([a-z]+ed)\b", re.I)
ACK = re.compile(r"^\W*(?:(?:sure|ok|okay|yes|yep|yeah|great|absolutely|of course|no problem|thanks|thank you)\b\W*)*"
                 r"(?:(?:i'll|i will|i can|i'm going to|i am going to)\s+(?:take care of|handle|do|work on|look into|get)\s+(?:it|this|that)(?:\s+done)?"
                 r"|(?:i'm|i am)\s+on\s+it|on\s+it|will\s+do|got\s+it)\b", re.I)


def _vstem(word: str) -> str:
    return stem(word.lower()).rstrip("e")


def _title_verb(title: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]+", title.lower()) if w not in {"please", "kindly"}]
    return words[0] if words else ""


def context_completion(sentence: str, tasks: Sequence[Any]) -> Optional[IntentHit]:
    s = sentence.strip()
    q = is_question(s)
    for rx in (PARTICIPLE, FIRST_PAST):
        for m in rx.finditer(s):
            part = m.group(1)
            hits = []
            for t in tasks:
                if t.status not in ("open", "in_progress"):
                    continue
                if _vstem(_title_verb(t.title)) != _vstem(part):
                    continue
                shared = (set(content_tokens(s, drop_filler=False)) & set(content_tokens(t.title, drop_filler=False))) - {stem(part.lower()), _vstem(part)}
                if shared:
                    hits.append(t.task_id)
            if not hits:
                continue
            if _gated(s, m, allow_question=False, question=q) is not None:
                return None
            return IntentHit(op="COMPLETE_TASK", cue=m.group(0), cue_span=(m.start(), m.end()), question=q,
                             extras={"form": "context_participle", "candidates": hits})
    return None


def owner_acknowledgement(sentence: str, tasks: Sequence[Any], speaker: Optional[str]) -> Optional[Any]:
    """The speaker's only open task, when the sentence is a bare 'I'll take care of it / on it / will do'."""
    s = sentence.strip()
    if not speaker or is_question(s) or not ACK.match(s):
        return None
    mine = [t for t in tasks if t.owner_id == speaker and t.status in ("open", "in_progress")]
    return mine[0] if len(mine) == 1 else None
