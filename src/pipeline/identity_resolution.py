"""Assignee resolution (Phase 4). Conservative: ambiguity is reported, never guessed.

Rules
- A named PERSON span resolves via exact alias/email, else a *unique* name token among participants.
- "I" resolves to the sender only when the task text carries a first-person commitment cue.
- "you"/imperatives resolve to a participant named as the addressee ("Bianca, please ...", "Bianca please ...", "..., Bianca."),
  even when the message went to several people; otherwise only when exactly one non-sender recipient exists.
- Collective words (all, everyone, team, organisations) are UNSUPPORTED_GROUP (GROUP is out of scope).
- Several different assignees -> AMBIGUOUS with basis "multiple_assignees"; owner stays null.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from src.pipeline.contracts import AssigneeResolution, MessageEnvelope, Participant

TITLE_RE = re.compile(r"^(mr|mrs|ms|miss|dr|prof)\.?\s+", re.I)
GROUP_WORDS = {"all", "everyone", "everybody", "team", "teams", "group", "anyone", "someone", "somebody", "folks",
               "guys", "staff", "department", "committee", "management", "enron", "both", "each", "others", "us", "we"}
SENT_BREAK = re.compile(r"[.!?]\s+|\n")
FIRST_SINGULAR = re.compile(r"\b(i will|i'll|i can|i shall|i'm going to|i am going to|i'd be happy to|i would|i'll be|let me|i plan to|i intend to|i'm happy to|i am happy to|i should|i need to|i have to|i must)\b", re.I)
FIRST_PLURAL = re.compile(r"\b(we will|we'll|we can|we shall|we should|we need to|we must|let's|let us|we have to)\b", re.I)
SECOND_PERSON = re.compile(r"\b(please|kindly|can you|could you|would you|will you|you will|you should|you need to|you must|you'll|you can|you might want to|i need you to|i'd like you to|i want you to)\b", re.I)
FIRST_PERSON_SPAN = {"i", "me", "myself"}
SECOND_PERSON_SPAN = {"you", "your", "yourself"}


def _norm(name: str) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip().lower()).strip(" .,;:'\"`")
    return TITLE_RE.sub("", name)


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[\s,.\-]+", _norm(name)) if len(t) > 1]


class ParticipantRegistry:
    def __init__(self, participants: Sequence[Participant]):
        self.participants = list(participants)
        self.by_id = {p.id: p for p in self.participants}

    @classmethod
    def from_json(cls, path: Path) -> "ParticipantRegistry":
        data = json.loads(Path(path).read_text())
        return cls([Participant(**p) for p in data["participants"]])

    def exact(self, name: str) -> list[Participant]:
        key = _norm(name)
        hits = []
        for p in self.participants:
            names = [p.display_name, *p.aliases, *p.emails]
            if key and any(key == _norm(n) for n in names):
                hits.append(p)
        return hits

    def by_token(self, name: str) -> list[Participant]:
        toks = _tokens(name)
        if len(toks) != 1:
            return []
        hits = []
        for p in self.participants:
            parts = {t for n in [p.display_name, *p.aliases] for t in _tokens(n)}
            if toks[0] in parts:
                hits.append(p)
        return hits


def resolve_name(raw: str, registry: ParticipantRegistry) -> AssigneeResolution:
    key = _norm(raw)
    if key in GROUP_WORDS:
        return AssigneeResolution(raw=raw, status="UNSUPPORTED_GROUP", basis="collective_word")
    hits = registry.exact(raw)
    if len(hits) == 1:
        return AssigneeResolution(raw=raw, status="RESOLVED", participant_id=hits[0].id, basis="exact_alias")
    if len(hits) > 1:
        return AssigneeResolution(raw=raw, status="AMBIGUOUS", candidates=[p.id for p in hits], basis="exact_alias_shared")
    hits = registry.by_token(raw)
    if len(hits) == 1:
        return AssigneeResolution(raw=raw, status="RESOLVED", participant_id=hits[0].id, basis="unique_name_token")
    if len(hits) > 1:
        return AssigneeResolution(raw=raw, status="AMBIGUOUS", candidates=[p.id for p in hits], basis="name_token_shared")
    return AssigneeResolution(raw=raw, status="UNKNOWN_PERSON", basis="no_participant_match")


def _sentence_window(text: str, task_span: Mapping[str, Any]) -> str:
    start = int(task_span["start"])
    breaks = [m.end() for m in SENT_BREAK.finditer(text[:start])]
    return text[(breaks[-1] if breaks else 0):int(task_span["end"])]


def resolve_assignee(person_spans: Sequence[Mapping[str, Any]], task_span: Mapping[str, Any],
                     envelope: MessageEnvelope, registry: ParticipantRegistry) -> AssigneeResolution:
    """Resolve the owner of one task. ``person_spans`` are the PERSON entities linked ASSIGNED_TO."""
    window = _sentence_window(envelope.text, task_span)
    sender_ok = envelope.sender_id in registry.by_id if envelope.sender_id else False

    if person_spans:
        resolutions = []
        for span in person_spans:
            raw = span["text"]
            n = _norm(raw)
            if n in FIRST_PERSON_SPAN:
                resolutions.append(_first_person(raw, window, envelope, sender_ok, require_cue=False))
            elif n in SECOND_PERSON_SPAN:
                resolutions.append(_second_person(raw, envelope))
            else:
                resolutions.append(resolve_name(raw, registry))
        distinct = {r.participant_id for r in resolutions if r.participant_id}
        if len(resolutions) == 1:
            return resolutions[0]
        if len(distinct) == 1 and all(r.participant_id for r in resolutions):
            return resolutions[0]  # several spans, all the same participant
        cands = sorted(distinct | {c for r in resolutions for c in r.candidates})
        raws = " | ".join(r.raw for r in resolutions if r.raw)
        return AssigneeResolution(raw=raws, status="AMBIGUOUS", candidates=cands, basis="multiple_assignees")

    # no linked PERSON span: look for evidence in the sentence
    if _plural_only(window):
        return AssigneeResolution(raw=None, status="UNASSIGNED", basis="first_person_plural")
    if FIRST_SINGULAR.search(window):
        return _first_person(None, window, envelope, sender_ok, require_cue=True)
    if SECOND_PERSON.search(window):
        named = _named_addressee(envelope, task_span, registry)
        return named or _second_person(None, envelope)
    return AssigneeResolution(raw=None, status="UNASSIGNED", basis="no_assignee_evidence")


NAME_WORD = re.compile(r"@?\b([A-Z][\w'-]+)\b")


def _named_addressee(envelope: MessageEnvelope, task_span: Mapping[str, Any], registry: ParticipantRegistry) -> Optional[AssigneeResolution]:
    """A request addressed to exactly one named participant: before the action ("Bianca please train ...") or as a trailing
    vocative ("Train the model, Bianca."). Used when the extractor linked no PERSON (it often misses a name without a comma).
    Several different names, or only the sender's own name, resolve nothing: the caller then falls back to the recipients."""
    text, start, end = envelope.text, int(task_span["start"]), int(task_span["end"])
    breaks = [m.end() for m in SENT_BREAK.finditer(text[:start])]
    before = text[(breaks[-1] if breaks else 0):start]
    nxt = SENT_BREAK.search(text, end)
    after = text[end:nxt.start() if nxt else len(text)]
    trailing = re.search(r",\s*@?([A-Z][\w'-]+)\s*[.!?]*\s*$", after)
    words = [m.group(1) for m in NAME_WORD.finditer(before)] + ([trailing.group(1)] if trailing else [])
    hits = {p.id: (w, p) for w in words for p in (registry.exact(w) or registry.by_token(w)) if p.id != envelope.sender_id}
    if len(hits) != 1:
        return None
    pid, (raw, _) = next(iter(hits.items()))
    return AssigneeResolution(raw=raw, status="RESOLVED", participant_id=pid, basis="named_addressee")


def _plural_only(window: str) -> bool:
    return bool(FIRST_PLURAL.search(window)) and not FIRST_SINGULAR.search(window)


def _first_person(raw, window, envelope, sender_ok, *, require_cue: bool) -> AssigneeResolution:
    if require_cue and not FIRST_SINGULAR.search(window):
        return AssigneeResolution(raw=raw, status="UNASSIGNED", basis="no_first_person_commitment")
    if not sender_ok:
        return AssigneeResolution(raw=raw, status="UNASSIGNED", basis="first_person_unknown_sender")
    return AssigneeResolution(raw=raw, status="RESOLVED_SENDER", participant_id=envelope.sender_id,
                              basis="first_person_commitment")


def _second_person(raw, envelope: MessageEnvelope) -> AssigneeResolution:
    others = [r for r in envelope.recipient_ids if r != envelope.sender_id]
    if len(others) == 1:
        return AssigneeResolution(raw=raw, status="RESOLVED_RECIPIENT", participant_id=others[0], basis="single_addressee")
    if len(others) > 1:
        return AssigneeResolution(raw=raw, status="UNASSIGNED", candidates=others, basis="multiple_recipients")
    return AssigneeResolution(raw=raw, status="UNASSIGNED", basis="no_recipient")


# ----------------------------------------------------------------------- low-trust MailEx helper
def _clean_mail_name(raw: str) -> tuple[str, Optional[str]]:
    raw = re.sub(r"\s+on\s+\d{1,2}/\d{1,2}/\d{2,4}.*$", "", raw.strip())
    email = None
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw)
    if m:
        email = m.group(0).lower()
    raw = re.sub(r"\[mailto:[^\]]*\]", "", raw)
    raw = re.sub(r"/[^\s]*@[^\s]*$", "", raw)       # 'Name/ENRON@enronXgate' -> 'Name'
    raw = re.sub(r"/(ET&S|ENRON|Enron|GCO)[^\s]*", "", raw).strip()
    if "@" in raw and email:
        raw = email.split("@")[0].replace(".", " ").replace("_", " ").title()
    return raw.strip(" ,;"), email


def _participant(raw: str, pid: str) -> Participant:
    name, email = _clean_mail_name(raw)
    if "," in name:                                  # 'Last, First M.' -> 'First M. Last'
        last, first = [x.strip() for x in name.split(",", 1)]
        display = f"{first} {last}".strip()
        aliases = [name, first, last]
    else:
        display = name
        aliases = [name.split()[0]] if len(name.split()) > 1 else []
    return Participant(id=pid, display_name=display, aliases=[a for a in aliases if a],
                       emails=[email] if email else [], low_trust=True)


def registry_from_mailex_record(record: Mapping[str, Any]):
    """Best-effort participant registry from noisy MailEx header fields. LOW TRUST: corpus experiments only.

    Recipients are often 'Last','First' pairs split on the comma, so an even-length list without
    '@' or '/' is re-paired; anything else is treated as one recipient per entry.
    """
    people: list[Participant] = []
    sender = record.get("sender")
    sender_id = None
    if sender:
        people.append(_participant(sender, "sender"))
        sender_id = "sender"
    rec = [r for r in (record.get("recipients") or []) if r]
    if rec and len(rec) % 2 == 0 and not any(("@" in r or "/" in r) for r in rec):
        rec = [f"{rec[i]}, {rec[i + 1]}" for i in range(0, len(rec), 2)]
    recipient_ids = []
    for i, r in enumerate(rec):
        pid = f"recipient_{i + 1}"
        people.append(_participant(r, pid))
        recipient_ids.append(pid)
    return ParticipantRegistry(people), sender_id, recipient_ids
