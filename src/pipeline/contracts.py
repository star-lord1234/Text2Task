"""Phase 4 data contracts. Plain dataclasses, JSON-serialisable via to_dict()."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

SCHEMA_VERSION = "phase4-v1"

TEMPORAL_STATUSES = ("RESOLVED", "PARTIAL", "AMBIGUOUS", "UNRESOLVED_NO_ANCHOR",
                     "UNRESOLVED_EVENT_CONDITION", "VAGUE", "UNPARSEABLE")
GRANULARITIES = ("DATE", "DATETIME", "TIME_ONLY", "PART_OF_DAY", "WEEK", "MONTH", "YEAR", "RANGE")
ASSIGNEE_STATUSES = ("RESOLVED", "RESOLVED_SENDER", "RESOLVED_RECIPIENT", "AMBIGUOUS", "UNKNOWN_PERSON",
                     "UNSUPPORTED_GROUP", "UNASSIGNED")
SEVERITIES = ("info", "warn", "block")


@dataclass
class MessageEnvelope:
    message_id: str
    text: str
    sender_id: Optional[str] = None
    recipient_ids: list[str] = field(default_factory=list)
    timestamp: Optional[str] = None       # ISO-8601 or None; never defaulted to the machine clock
    timezone: Optional[str] = None        # IANA name or None
    thread_id: Optional[str] = None
    in_reply_to: Optional[str] = None     # message_id this message replies to (Phase 5 matching signal)


@dataclass
class Participant:
    id: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    low_trust: bool = False


@dataclass
class TemporalValue:
    raw: str
    status: str = "UNPARSEABLE"
    granularity: Optional[str] = None
    start: Optional[str] = None           # ISO date or datetime
    end: Optional[str] = None
    value: Optional[str] = None           # point value when the expression denotes one instant/date
    part_of_day: Optional[str] = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    anchor_used: Optional[str] = None
    assumptions: list[str] = field(default_factory=list)
    rule_id: Optional[str] = None
    in_past: Optional[bool] = None
    deadline_phrase: bool = False         # raw text itself carried by/before/due/until...

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssigneeResolution:
    raw: Optional[str]
    status: str = "UNASSIGNED"
    participant_id: Optional[str] = None
    candidates: list[str] = field(default_factory=list)
    basis: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Flag:
    code: str
    severity: str
    field: str
    message: str
    question: Optional[str] = None
    evidence: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskCandidate:
    candidate_id: str
    message_id: str
    title: str
    task_span: dict[str, Any]
    assignee: AssigneeResolution
    due: Optional[TemporalValue] = None
    scheduled: Optional[TemporalValue] = None
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    review_required: bool = True
    provenance: dict[str, Any] = field(default_factory=dict)
    evidence_text: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
