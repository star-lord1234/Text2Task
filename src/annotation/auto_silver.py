"""Conservative deterministic SILVER conversion from MailEx event signals."""

from __future__ import annotations

import ast
import copy
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.annotation.validators import validate_record


VERSION = "mailex-auto-silver-v1.0.0"
DIRECT_TASK_EVENTS = {
    "Request_Action",
    "Deliver_Action_Data",
    "Request_Action_Data",
    "Amend_Action_Data",
    "Request_Meeting",
    "Request_Meeting_Data",
    "Deliver_Meeting_Data",
    "Amend_Meeting_Data",
    "Request_Data",
    "Deliver_Data",
    "Amend_Data",
}
PRONOUN_OR_GENERIC = {
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "him", "his",
    "she", "her", "hers", "they", "them", "their", "everyone", "anyone", "someone",
    "dad", "mom", "son", "customer", "customers", "client", "clients", "management",
}
GROUP_TERMS = {
    "team", "committee", "department", "group", "desk", "operations", "community",
    "directors", "employees", "board", "legal", "finance", "marketing", "hr",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    values = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected object at {path}:{line_number}")
            values.append(value)
    return values


def atomic_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


@dataclass(frozen=True)
class TokenSpan:
    role: str
    token_start: int
    token_end: int


LABEL_RE = re.compile(r"(?:(Context|Revision):\s*)?([BI])-(.+)$", re.I)


def parse_label(label: str) -> tuple[str, str] | None:
    match = LABEL_RE.search(label)
    if not match:
        return None
    qualifier, prefix, role = match.groups()
    normalized_role = re.sub(r"\s+", " ", role.strip())
    if qualifier:
        normalized_role = f"{qualifier.title()}: {normalized_role}"
    return prefix.upper(), normalized_role


def decode_spans(labels: Sequence[str]) -> list[TokenSpan]:
    spans: list[TokenSpan] = []
    active_role: str | None = None
    active_start = 0
    for index, raw_label in enumerate(list(labels) + ["O"]):
        parsed = parse_label(str(raw_label))
        if parsed is None:
            if active_role is not None:
                spans.append(TokenSpan(active_role, active_start, index))
                active_role = None
            continue
        prefix, role = parsed
        if prefix == "B" or active_role != role:
            if active_role is not None:
                spans.append(TokenSpan(active_role, active_start, index))
            active_role, active_start = role, index
    return spans


def trigger_token_span(trigger: Any, token_count: int) -> tuple[int, int] | None:
    if not isinstance(trigger, str) or not trigger.strip():
        return None
    try:
        parsed = ast.literal_eval(trigger)
    except (ValueError, SyntaxError):
        parsed = None
    indices_value = parsed.get("indices") if isinstance(parsed, dict) else None
    if indices_value is None:
        match = re.search(r"indices['\"]?\s*:\s*['\"]([^'\"]+)", trigger)
        indices_value = match.group(1) if match else None
    if not isinstance(indices_value, str):
        return None
    indices = [int(value) for value in re.findall(r"\d+", indices_value)]
    if not indices or min(indices) < 0 or max(indices) >= token_count:
        return None
    return min(indices), max(indices) + 1


def char_span(token_span: tuple[int, int], offsets: Sequence[Sequence[int]], text: str) -> tuple[int, int, str] | None:
    token_start, token_end = token_span
    if not (0 <= token_start < token_end <= len(offsets)):
        return None
    start, end = int(offsets[token_start][0]), int(offsets[token_end - 1][1])
    if not (0 <= start < end <= len(text)):
        return None
    surface = text[start:end]
    if not surface.strip():
        return None
    return start, end, surface


def member_entity_type(surface: str) -> str | None:
    words = re.findall(r"[A-Za-z]+", surface)
    lowered = {word.casefold() for word in words}
    if not words or lowered & PRONOUN_OR_GENERIC:
        return None
    if lowered & GROUP_TERMS:
        return "GROUP"
    title_like = sum(word[:1].isupper() or word.isupper() for word in words)
    if title_like == len(words) and len(words) <= 5:
        return "PERSON"
    return None


def _role_contains(role: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", role, flags=re.I) is not None


def _relation_evidence(first: Mapping[str, Any], second: Mapping[str, Any], text: str) -> dict[str, Any]:
    start = min(int(first["start"]), int(second["start"]))
    end = max(int(first["end"]), int(second["end"]))
    return {"start": start, "end": end, "text": text[start:end]}


def _task_state(event_type: str, surface: str) -> tuple[str, str, list[str], bool]:
    lowered = surface.casefold()
    if re.search(r"\b(cancel|cancelled|canceled|withdraw|stop)\b", lowered):
        return "CANCEL", "PENDING" if event_type.startswith("Request") else "CANCELED", [], False
    if re.search(r"\b(completed|finished|delivered|sent|reviewed|updated|attached)\b", lowered) and event_type.startswith("Deliver"):
        return "COMPLETE", "COMPLETED", [], False
    if event_type.startswith("Request"):
        return "CREATE", "PENDING", [], False
    if event_type.startswith("Amend"):
        return "UPDATE", "PENDING", [], True
    return "UNKNOWN", "UNKNOWN", ["OPERATION", "STATUS"], True


def _temporal_relation_type(event_type: str, temporal_surface: str) -> tuple[str, bool]:
    if "Meeting" in event_type:
        return "SCHEDULED_ON", False
    if re.search(r"\b(by|due|deadline|no later|until|as soon as)\b", temporal_surface, flags=re.I):
        return "DUE_ON", False
    return "SCHEDULED_ON", True


class AnnotationBuilder:
    def __init__(self, record: Mapping[str, Any]) -> None:
        self.record = record
        self.text = str(record.get("text", ""))
        self.tokens = list(record.get("tokens") or [])
        self.offsets = list(record.get("token_offsets") or [])
        self.entities: list[dict[str, Any]] = []
        self.entity_keys: dict[tuple[str, int, int], str] = {}
        self.relations: list[dict[str, Any]] = []
        self.tasks: list[dict[str, Any]] = []
        self.notes: list[str] = [f"Automatically generated SILVER annotation using {VERSION}; requires human verification for gold use."]

    def entity(self, entity_type: str, span: tuple[int, int, str], task_attributes: dict[str, Any] | None = None) -> dict[str, Any]:
        start, end, surface = span
        key = (entity_type, start, end)
        existing_id = self.entity_keys.get(key)
        if existing_id:
            return next(entity for entity in self.entities if entity["id"] == existing_id)
        entity = {
            "id": f"e{len(self.entities) + 1}",
            "type": entity_type,
            "start": start,
            "end": end,
            "text": surface,
            "task_attributes": task_attributes if entity_type == "TASK" else None,
        }
        self.entities.append(entity)
        self.entity_keys[key] = entity["id"]
        if entity_type == "TASK":
            self.tasks.append(entity)
        return entity

    def relation(self, relation_type: str, source: Mapping[str, Any], target: Mapping[str, Any], *, ambiguous: bool, inferred: bool = False) -> None:
        key = (relation_type, source["id"], target["id"])
        if any((relation["type"], relation["source_entity_id"], relation["target_entity_id"]) == key for relation in self.relations):
            return
        self.relations.append({
            "id": f"r{len(self.relations) + 1}",
            "type": relation_type,
            "source_entity_id": source["id"],
            "target_entity_id": target["id"],
            "relation_evidence": _relation_evidence(source, target, self.text),
            "explicit_vs_inferred": "INFERRED" if inferred else "EXPLICIT",
            "ambiguous": ambiguous,
        })

    def add_occurrence(self, event_type: str, labels: Sequence[str], trigger: Any) -> None:
        if event_type not in DIRECT_TASK_EVENTS:
            return
        decoded = decode_spans(labels)
        role_spans: list[tuple[str, tuple[int, int, str]]] = []
        for span in decoded:
            converted = char_span((span.token_start, span.token_end), self.offsets, self.text)
            if converted is not None:
                role_spans.append((span.role, converted))

        task_candidates = [span for role, span in role_spans if "action description" in role.casefold()]
        if not task_candidates:
            parsed_trigger = trigger_token_span(trigger, len(self.tokens))
            converted_trigger = char_span(parsed_trigger, self.offsets, self.text) if parsed_trigger else None
            if converted_trigger is not None:
                task_candidates = [converted_trigger]
        if not task_candidates:
            return

        member_spans = [(role, span) for role, span in role_spans if "member" in role.casefold() or "owner" in role.casefold()]
        temporal_spans = [(role, span) for role, span in role_spans if _role_contains(role, "date") or _role_contains(role, "time")]
        artifact_spans = [span for role, span in role_spans if "idstring" in role.casefold()]

        for task_span in task_candidates:
            member_entities = []
            for _role, span in member_spans:
                entity_type = member_entity_type(span[2])
                if entity_type:
                    member_entities.append(self.entity(entity_type, span))
            temporal_entities = [self.entity("TEMPORAL", span) for _role, span in temporal_spans]
            for span in artifact_spans:
                self.entity("ARTIFACT", span)

            operation, status, unresolved_state, ambiguous = _task_state(event_type, task_span[2])
            missing_fields: list[str] = []
            unresolved_fields = list(unresolved_state)
            if not member_entities:
                (unresolved_fields if member_spans else missing_fields).append("ASSIGNEE")
            if not temporal_entities:
                (unresolved_fields if temporal_spans else missing_fields).append("TEMPORAL")
            task_attributes = {
                "operation": operation,
                "status": status,
                "negated": bool(re.search(r"\b(?:not|never|cannot|can't|do not|don't)\b", task_span[2], flags=re.I)),
                "ambiguous": ambiguous or bool(unresolved_fields),
                "missing_fields": sorted(set(missing_fields)),
                "unresolved_fields": sorted(set(unresolved_fields)),
                "thread_task_id": None,
                "identity_status": "LOCAL_ONLY",
            }
            task = self.entity("TASK", task_span, task_attributes)
            for member in member_entities:
                self.relation("ASSIGNED_TO", task, member, ambiguous=False)
            for temporal in temporal_entities:
                relation_type, temporal_ambiguous = _temporal_relation_type(event_type, temporal["text"])
                self.relation(relation_type, task, temporal, ambiguous=temporal_ambiguous)

    def add_high_confidence_dependency(self) -> None:
        matches = (
            (self.record.get("candidate_selection") or {})
            .get("selection_signals", {})
            .get("prerequisite_matches", [])
        )
        high = [match for match in matches if match.get("confidence") == "provisional_high"]
        if not high or not self.tasks:
            return
        for match in high:
            connector_span = match.get("span")
            if not (isinstance(connector_span, list) and len(connector_span) == 2):
                continue
            connector_start, connector_end = map(int, connector_span)
            clause_start = connector_end
            while clause_start < len(self.text) and self.text[clause_start].isspace():
                clause_start += 1
            punctuation = re.search(r"[.;!?\n]", self.text[clause_start:clause_start + 180])
            clause_end = clause_start + (punctuation.start() if punctuation else min(120, len(self.text) - clause_start))
            while clause_end > clause_start and self.text[clause_end - 1].isspace():
                clause_end -= 1
            if clause_end <= clause_start:
                continue
            event = self.entity("EVENT", (clause_start, clause_end, self.text[clause_start:clause_end]))
            task = min(self.tasks, key=lambda item: min(abs(int(item["start"]) - connector_start), abs(int(item["end"]) - connector_end)))
            self.relation("DEPENDS_ON", task, event, ambiguous=True, inferred=False)
            self.notes.append(f"High-confidence dependency candidate retained for semantic review: {match.get('connector')!r}.")

    def annotation(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "annotation_status": "DRAFT",
            "annotator_id": f"auto-silver:{VERSION}",
            "entities": self.entities,
            "relations": self.relations,
            "relation_candidates": [],
            "reference_resolution": {"status": "DEFERRED_NO_REFERENCE_SPANS", "mentions": []},
            "notes": self.notes,
        }


def annotate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    builder = AnnotationBuilder(record)
    events = record.get("original_events") or {}
    for event_type, container in events.items():
        if not isinstance(container, dict):
            continue
        labels_list = container.get("labels") or []
        triggers = container.get("triggers") or []
        for index, labels in enumerate(labels_list):
            if not isinstance(labels, list):
                continue
            trigger = triggers[index] if index < len(triggers) else ""
            builder.add_occurrence(str(event_type), labels, trigger)
    builder.add_high_confidence_dependency()
    output = copy.deepcopy(dict(record))
    output["text2task_annotations"] = builder.annotation()
    output["llm_annotation_metadata"] = {
        "pipeline_version": VERSION,
        "provider": "deterministic_mail_ex_conversion",
        "model": "none",
        "timestamp": utc_now(),
        "source_record_id": record.get("id"),
        "source_split": record.get("source_split"),
        "annotation_status": "DRAFT",
        "requires_human_review_for_gold": True,
        "quality_tier": "SILVER",
        "signals": "original MailEx event instances plus conservative deterministic mapping",
    }
    return output


def annotate_jsonl(input_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    records = read_jsonl(input_path)
    outputs = []
    counters: Counter[str] = Counter()
    failures = []
    for record in records:
        output = annotate_record(record)
        issues = validate_record(output, require_annotations=True)
        if issues:
            failures.append({"record_id": record.get("id"), "issues": [asdict(issue) for issue in issues]})
            continue
        annotations = output["text2task_annotations"]
        tasks = [entity for entity in annotations["entities"] if entity["type"] == "TASK"]
        outputs.append(output)
        counters["records"] += 1
        counters["empty_task_records"] += not tasks
        counters["tasks"] += len(tasks)
        counters["entities"] += len(annotations["entities"])
        counters["relations"] += len(annotations["relations"])
        counters["dependencies"] += sum(relation["type"] == "DEPENDS_ON" for relation in annotations["relations"])
        counters["multiple_task_records"] += len(tasks) > 1
    atomic_jsonl(Path(output_path), outputs)
    return {
        "version": VERSION,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "input_records": len(records),
        "valid_outputs": len(outputs),
        "validation_failures": failures,
        **dict(counters),
    }
