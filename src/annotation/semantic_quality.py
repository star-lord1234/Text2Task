"""Conservative semantic warning checks for Text2Task SILVER-v2 annotations.

Warnings are review gates, never silent semantic repairs.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping


ACTION_SIGNAL = re.compile(
    r"\b(please|must|should|need(?:s)?\s+to|will|shall|plan(?:s|ned)?\s+to|"
    r"going\s+to|would\s+like|can\s+you|could\s+you|let\s+me\s+know|"
    r"do\s+not|don't|try\s+to|remember\s+to|send|review|prepare|schedule|"
    r"submit|provide|update|complete|call|contact|meet|attend|reserve|"
    r"investigate|check|approve|sign|return|forward|include|notify)\b",
    re.I,
)
HISTORICAL_SIGNAL = re.compile(
    r"\b(was|were|had|did|has\s+(?:already\s+)?(?:sent|filed|completed|approved|"
    r"changed|moved|received|submitted|signed|called)|yesterday\s+we|last\s+week\s+we)\b",
    re.I,
)
DESCRIPTIVE_SIGNAL = re.compile(
    r"\b(is|are|was|were|remain(?:s|ed)?|contains?|includes?|attached|available|"
    r"disrupted|rejected|received)\b",
    re.I,
)
PRONOUN_ONLY = re.compile(r"^(i|we|you|he|she|they|it|this|that)$", re.I)


@dataclass(frozen=True)
class SemanticWarning:
    code: str
    severity: str
    entity_id: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def spans_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return int(left["start"]) < int(right["end"]) and int(right["start"]) < int(left["end"])


def semantic_warnings(record: Mapping[str, Any]) -> list[SemanticWarning]:
    annotations = record.get("text2task_annotations") or {}
    entities = annotations.get("entities") or []
    tasks = [entity for entity in entities if entity.get("type") == "TASK"]
    warnings: list[SemanticWarning] = []
    for task in tasks:
        surface = str(task.get("text", "")).strip()
        entity_id = str(task.get("id")) if task.get("id") is not None else None
        words = re.findall(r"\b\w+\b", surface)
        attributes = task.get("task_attributes") or {}
        operation = attributes.get("operation")
        status = attributes.get("status")
        if not words or PRONOUN_ONLY.fullmatch(surface):
            warnings.append(SemanticWarning("task_fragment", "severe", entity_id, "TASK is empty or pronoun-only"))
        if len(words) > 30:
            warnings.append(SemanticWarning("overlong_task", "review", entity_id, "TASK exceeds 30 words"))
        if HISTORICAL_SIGNAL.search(surface) and not ACTION_SIGNAL.search(surface):
            warnings.append(SemanticWarning("historical_task", "severe", entity_id, "TASK appears to be completed history without an action signal"))
        if DESCRIPTIVE_SIGNAL.search(surface) and not ACTION_SIGNAL.search(surface) and operation == "CREATE":
            warnings.append(SemanticWarning("descriptive_task", "severe", entity_id, "CREATE TASK appears descriptive rather than actionable"))
        if status == "COMPLETED" and attributes.get("identity_status") != "RESOLVED":
            warnings.append(SemanticWarning("unresolved_completed_task", "severe", entity_id, "Completed TASK lacks resolved cross-email identity"))
    for index, left in enumerate(tasks):
        for right in tasks[index + 1:]:
            if spans_overlap(left, right):
                warnings.append(SemanticWarning(
                    "nested_or_overlapping_tasks", "severe", str(left.get("id")),
                    f"TASK overlaps TASK {right.get('id')}",
                ))
    for task in tasks:
        for temporal in (entity for entity in entities if entity.get("type") == "TEMPORAL"):
            if spans_overlap(task, temporal):
                warnings.append(SemanticWarning(
                    "task_temporal_overlap", "review", str(task.get("id")),
                    f"TASK overlaps TEMPORAL {temporal.get('id')}",
                ))
    return warnings


def semantic_quality(record: Mapping[str, Any]) -> dict[str, Any]:
    warnings = semantic_warnings(record)
    severe = [warning for warning in warnings if warning.severity == "severe"]
    return {
        "passed_for_training": not severe,
        "severe_count": len(severe),
        "warning_count": len(warnings),
        "warnings": [warning.to_dict() for warning in warnings],
    }
