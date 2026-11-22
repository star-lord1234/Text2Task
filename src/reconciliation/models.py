"""Phase 5 data models: tasks, proposed operations, history, dependency edges."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dc_field
from typing import Any, Optional

SCHEMA_VERSION = "phase5-v1"

OPERATIONS = ("CREATE_TASK", "UPDATE_ASSIGNEE", "PROPOSE_DUE_DATE_CHANGE", "CONFIRM_DUE_DATE_CHANGE", "UPDATE_STATUS",
              "COMPLETE_TASK", "CANCEL_TASK", "ADD_DEPENDENCY", "NO_ACTION")
STATUSES = ("open", "in_progress", "completed", "cancelled")   # `blocked` is derived (Phase 6), never stored
PROPOSAL_STATUSES = ("pending", "applied", "dismissed", "superseded", "no_action")
SOURCE_KINDS = ("neural", "rule", "scripted", "human")
ALLOWED_TRANSITIONS = {
    "open": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


@dataclass
class Task:
    task_id: str
    workspace_id: str
    thread_id: str
    title: str
    aliases: list[str] = dc_field(default_factory=list)
    owner_id: Optional[str] = None
    due: Optional[dict[str, Any]] = None
    scheduled: Optional[dict[str, Any]] = None
    status: str = "open"
    source_message_id: Optional[str] = None
    evidence_text: str = ""
    version: int = 1
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    last_touched_message_id: Optional[str] = None
    last_touched_seq: int = 0
    provenance: dict[str, Any] = dc_field(default_factory=dict)
    pending_changes: dict[str, Any] = dc_field(default_factory=dict)   # {"due": {...}, "scheduled": {...}}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProposedOperation:
    proposal_id: str
    workspace_id: str
    message_id: str
    operation: str
    task_id: Optional[str] = None
    field: Optional[str] = None
    before: Any = None
    after: Any = None
    base_version: Optional[int] = None
    payload: dict[str, Any] = dc_field(default_factory=dict)
    evidence: dict[str, Any] = dc_field(default_factory=dict)
    match: dict[str, Any] = dc_field(default_factory=dict)
    flags: list[dict[str, Any]] = dc_field(default_factory=list)
    needs_confirmation_from: list[str] = dc_field(default_factory=list)
    status: str = "pending"
    source_kind: str = "rule"
    proposer_id: Optional[str] = None
    note: str = ""
    created_at: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution_note: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def review_required(self) -> bool:
        return any(f.get("severity") != "info" for f in self.flags)


@dataclass
class HistoryEvent:
    event_id: Optional[int]
    workspace_id: str
    task_id: str
    proposal_id: Optional[str]
    message_id: Optional[str]
    actor: Optional[str]
    operation: str
    field: str
    before: Any
    after: Any
    timestamp: str
    source_kind: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DependencyEdge:
    edge_id: str
    workspace_id: str
    dependent_task_id: str
    prerequisite_task_id: str
    status: str = "proposed"            # proposed | accepted | rejected
    evidence: str = ""
    source_message_id: Optional[str] = None
    source_kind: str = "rule"
    score: Optional[float] = None
    reason: str = ""
    proposal_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconcileResult:
    message_id: str
    proposals: list[ProposedOperation] = dc_field(default_factory=list)
    no_actions: list[ProposedOperation] = dc_field(default_factory=list)   # terminal NO_ACTION, nothing to review
    replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"message_id": self.message_id, "replayed": self.replayed,
                "proposals": [p.to_dict() for p in self.proposals], "no_actions": [p.to_dict() for p in self.no_actions]}


class StaleVersion(Exception):
    """Raised when the task changed since the proposal/reviewer view; nothing is written."""

    def __init__(self, task_id: str, expected: int, actual: int):
        super().__init__(f"{task_id}: expected version {expected}, found {actual}")
        self.task_id, self.expected, self.actual = task_id, expected, actual


class ReconciliationError(Exception):
    """A rejected change with a machine-readable code (nothing written)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
