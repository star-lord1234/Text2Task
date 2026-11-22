"""Request/response models (Pydantic). Response models are intentionally light on nesting: complex nested records are typed as
dictionaries whose keys are documented in docs/openapi.json and the Phase 7 plan."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ParticipantModel(BaseModel):
    id: str
    name: str
    role: Optional[str] = None
    color: str


class MessageCreate(BaseModel):
    sender_id: str
    recipient_ids: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1, max_length=4000)
    mode: Literal["scripted", "live"] = "live"
    created_at: Optional[str] = Field(default=None, description="Simulated message time (ISO-8601 with offset). Defaults to now in the workspace timezone.")
    in_reply_to: Optional[str] = None


class AcceptBody(BaseModel):
    actor_id: str
    edits: Optional[dict[str, Any]] = None
    expected_version: Optional[int] = None
    idempotency_key: Optional[str] = None


class DismissBody(BaseModel):
    actor_id: str
    reason: str = ""


class TaskPatch(BaseModel):
    actor_id: str
    expected_version: int
    changes: dict[str, Any]


class EdgeCreate(BaseModel):
    actor_id: str
    prerequisite_task_id: str
    dependent_task_id: str
    evidence: str = ""


class EdgeAction(BaseModel):
    actor_id: str
    reason: str = ""


class SettingsUpdate(BaseModel):
    timezone: Optional[str] = None
    allow_rule_fallback: Optional[bool] = None
    rule_dependency_linker: Optional[bool] = None
    pipeline_preset: Optional[str] = Field(default=None, description="neural_only | neural_plus_linker | refined | hybrid | rule_only")
    refine_overrides: Optional[dict[str, bool]] = Field(default=None, description="Per-stage switches that override the preset.")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[dict[str, Any]] = None
