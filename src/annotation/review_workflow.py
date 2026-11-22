"""Human review and quality-control utilities for Text2Task annotations.

Review documents are deliberately separate from source records and LLM output.
The reviewer edits ``working_annotation`` while ``original_prediction`` remains
immutable, which makes every correction auditable and reversible.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.annotation.validators import ValidationIssue, validate_record


REVIEW_SCHEMA_VERSION = "1.0.0"
QUALITY_TIERS = {"GOLD", "SILVER", "REJECTED"}
REVIEW_MODES = {"INDEPENDENT", "VERIFY"}
ENTITY_TYPES = {"TASK", "PERSON", "GROUP", "TEMPORAL", "EVENT", "ARTIFACT"}
RELATION_TYPES = {"ASSIGNED_TO", "DUE_ON", "SCHEDULED_ON", "DEPENDS_ON"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def blank_annotation(annotator_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "annotation_status": "DRAFT",
        "annotator_id": annotator_id,
        "entities": [],
        "relations": [],
        "relation_candidates": [],
        "reference_resolution": {
            "status": "DEFERRED_NO_REFERENCE_SPANS",
            "mentions": [],
        },
        "notes": [],
    }


def default_task_attributes() -> dict[str, Any]:
    """Conservative valid placeholder for a newly created human TASK span."""

    return {
        "operation": "UNKNOWN",
        "status": "UNKNOWN",
        "negated": False,
        "ambiguous": True,
        "missing_fields": ["ASSIGNEE", "TEMPORAL"],
        "unresolved_fields": ["OPERATION", "STATUS"],
        "thread_task_id": None,
        "identity_status": "LOCAL_ONLY",
    }


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            values.append(value)
    return values


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def review_filename(record_id: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "_", record_id).strip("._-")[:80] or "record"
    digest = hashlib.sha256(record_id.encode("utf-8")).hexdigest()[:12]
    return f"{readable}.{digest}.review.json"


def _index_records(paths: Sequence[Path | str], key: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        for record in read_jsonl(path):
            identifier = record.get(key)
            if not isinstance(identifier, str):
                raise ValueError(f"Missing string {key!r} in {path}")
            if identifier in result:
                raise ValueError(f"Duplicate record ID {identifier!r} across {path}")
            result[identifier] = record
    return result


def make_review_document(
    source_record: Mapping[str, Any],
    prediction_record: Mapping[str, Any] | None = None,
    failure_record: Mapping[str, Any] | None = None,
    *,
    mode: str = "INDEPENDENT",
) -> dict[str, Any]:
    mode = mode.upper()
    if mode not in REVIEW_MODES:
        raise ValueError(f"Unsupported review mode: {mode}")
    record_id = source_record.get("id")
    split = source_record.get("source_split")
    if not isinstance(record_id, str) or not isinstance(split, str):
        raise ValueError("Source record requires string id and source_split")
    original_prediction = None
    prediction_metadata = None
    if prediction_record is not None:
        original_prediction = copy.deepcopy(prediction_record.get("text2task_annotations"))
        prediction_metadata = copy.deepcopy(prediction_record.get("llm_annotation_metadata"))
    working = copy.deepcopy(original_prediction) if mode == "VERIFY" and original_prediction is not None else blank_annotation()
    document = {
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "record_id": record_id,
        "source_split": split,
        "review_mode": mode,
        "review_status": "PENDING",
        "quality_tier": None,
        # Test outcomes are never eligible for prompt or training-selection feedback.
        "prompt_feedback_eligible": split != "test",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "source_record": copy.deepcopy(dict(source_record)),
        "source_record_hash": canonical_hash(source_record),
        "original_prediction": original_prediction,
        "original_prediction_hash": canonical_hash(original_prediction),
        "original_prediction_metadata": prediction_metadata,
        "original_failure": copy.deepcopy(failure_record),
        "working_annotation": working,
        "reviewer": {
            "reviewer_id": None,
            "started_at": None,
            "completed_at": None,
            "notes": [],
        },
        "correction_events": [],
        "acknowledged_warnings": [],
        "validation": {},
    }
    document["validation"] = validate_review_document(document)
    return document


def prepare_review_documents(
    source_paths: Sequence[Path | str],
    prediction_paths: Sequence[Path | str],
    failure_paths: Sequence[Path | str],
    output_root: Path | str,
    *,
    mode: str = "AUTO",
    limit: int | None = None,
    overwrite: bool = False,
) -> dict[str, int]:
    predictions = _index_records(prediction_paths, "id") if prediction_paths else {}
    failures = _index_records(failure_paths, "source_record_id") if failure_paths else {}
    output_root = Path(output_root)
    counts: Counter[str] = Counter()
    processed = 0
    for source_path in source_paths:
        for source in read_jsonl(source_path):
            if limit is not None and processed >= limit:
                return dict(counts)
            record_id = source.get("id")
            split = source.get("source_split")
            if not isinstance(record_id, str) or not isinstance(split, str):
                raise ValueError(f"Source record lacks id/source_split: {source_path}")
            resolved_mode = mode.upper()
            if resolved_mode == "AUTO":
                resolved_mode = "INDEPENDENT" if split in {"dev", "test"} else "VERIFY"
            path = output_root / split / review_filename(record_id)
            if path.exists():
                if not overwrite:
                    counts["existing"] += 1
                    processed += 1
                    continue
                existing = load_review(path)
                reviewer = existing.get("reviewer") or {}
                if existing.get("review_status") != "PENDING" or existing.get("correction_events") or reviewer.get("started_at"):
                    raise ValueError(f"Refusing to overwrite a review after human work started: {path}")
            document = make_review_document(
                source,
                predictions.get(record_id),
                failures.get(record_id),
                mode=resolved_mode,
            )
            atomic_json(path, document)
            counts["created"] += 1
            counts[f"created_{split}"] += 1
            counts[f"mode_{resolved_mode.lower()}"] += 1
            if record_id in predictions:
                counts["with_prediction"] += 1
            if record_id in failures:
                counts["with_failure"] += 1
            processed += 1
    return dict(counts)


def load_review(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("review_schema_version") != REVIEW_SCHEMA_VERSION:
        raise ValueError(f"Not a Text2Task review document: {path}")
    return value


def save_review(path: Path | str, document: dict[str, Any]) -> None:
    document["updated_at"] = utc_now()
    document["validation"] = validate_review_document(document)
    atomic_json(Path(path), document)


def _qc_issue(path: str, code: str, message: str, severity: str = "WARNING") -> dict[str, str]:
    return {"path": path, "code": code, "message": message, "severity": severity}


def _overlaps(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    starts = (first.get("start"), second.get("start"))
    ends = (first.get("end"), second.get("end"))
    return all(isinstance(value, int) for value in (*starts, *ends)) and starts[0] < ends[1] and starts[1] < ends[0]


def _dependency_cycles(relations: Sequence[Mapping[str, Any]]) -> set[str]:
    graph: dict[str, set[str]] = defaultdict(set)
    relation_ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    for relation in relations:
        if relation.get("type") != "DEPENDS_ON":
            continue
        source, target = relation.get("source_entity_id"), relation.get("target_entity_id")
        if isinstance(source, str) and isinstance(target, str):
            graph[source].add(target)
            relation_ids[(source, target)].append(str(relation.get("id", "")))
    cyclic: set[str] = set()
    for origin in graph:
        stack = [(origin, iter(graph.get(origin, ())))]
        active = {origin}
        path = [origin]
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
            except StopIteration:
                active.discard(node)
                path.pop()
                stack.pop()
                continue
            if child in active:
                cycle_nodes = path[path.index(child):] + [child]
                for left, right in zip(cycle_nodes, cycle_nodes[1:]):
                    cyclic.update(relation_ids.get((left, right), []))
            elif child in graph:
                active.add(child)
                path.append(child)
                stack.append((child, iter(graph.get(child, ()))))
    return cyclic


def validate_review_document(document: Mapping[str, Any]) -> dict[str, Any]:
    source = document.get("source_record")
    annotation = document.get("working_annotation")
    schema_issues: list[ValidationIssue] = []
    qc_issues: list[dict[str, str]] = []
    if canonical_hash(source) != document.get("source_record_hash"):
        qc_issues.append(_qc_issue("$.source_record", "source_snapshot_modified", "immutable source snapshot hash does not match", "ERROR"))
    if canonical_hash(document.get("original_prediction")) != document.get("original_prediction_hash"):
        qc_issues.append(_qc_issue("$.original_prediction", "original_prediction_modified", "immutable LLM prediction hash does not match", "ERROR"))
    if document.get("source_split") == "test" and document.get("prompt_feedback_eligible") is not False:
        qc_issues.append(_qc_issue("$.prompt_feedback_eligible", "test_feedback_leak", "test outcomes must remain ineligible for prompt/model-selection feedback", "ERROR"))
    review_status, quality_tier = document.get("review_status"), document.get("quality_tier")
    reviewer = document.get("reviewer") or {}
    if review_status == "COMPLETED" and quality_tier not in QUALITY_TIERS:
        qc_issues.append(_qc_issue("$.quality_tier", "completed_without_tier", "completed review requires GOLD, SILVER, or REJECTED", "ERROR"))
    if review_status == "COMPLETED" and (not reviewer.get("reviewer_id") or not reviewer.get("completed_at")):
        qc_issues.append(_qc_issue("$.reviewer", "completed_without_reviewer", "completed review requires reviewer identity and completion time", "ERROR"))
    if review_status != "COMPLETED" and quality_tier is not None:
        qc_issues.append(_qc_issue("$.quality_tier", "premature_quality_tier", "quality tier may only be assigned by completed human review", "ERROR"))
    if not isinstance(source, dict):
        qc_issues.append(_qc_issue("$.source_record", "source_missing", "source record is missing", "ERROR"))
    else:
        candidate = copy.deepcopy(source)
        candidate["text2task_annotations"] = copy.deepcopy(annotation)
        schema_issues = validate_record(candidate, require_annotations=True)

    annotations = annotation if isinstance(annotation, dict) else {}
    entities = annotations.get("entities", []) if isinstance(annotations.get("entities", []), list) else []
    relations = annotations.get("relations", []) if isinstance(annotations.get("relations", []), list) else []
    by_id = {entity.get("id"): entity for entity in entities if isinstance(entity, dict)}

    seen_pairs: dict[tuple[Any, Any], set[str]] = defaultdict(set)
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            continue
        path = f"$.working_annotation.relations[{index}]"
        relation_type = relation.get("type")
        if relation_type == "DEPENDS_ON":
            qc_issues.append(_qc_issue(path, "dependency_semantic_review_required", "confirm this is a genuine prerequisite, not temporal order"))
        source_entity = by_id.get(relation.get("source_entity_id"))
        target_entity = by_id.get(relation.get("target_entity_id"))
        evidence = relation.get("relation_evidence")
        if isinstance(evidence, dict) and isinstance(source_entity, dict) and isinstance(target_entity, dict):
            if not _overlaps(evidence, source_entity) and not _overlaps(evidence, target_entity):
                qc_issues.append(_qc_issue(path, "unsupported_relation_evidence", "evidence overlaps neither relation endpoint", "ERROR"))
        pair = (relation.get("source_entity_id"), relation.get("target_entity_id"))
        seen_pairs[pair].add(str(relation_type))

    for pair, types in seen_pairs.items():
        if {"DUE_ON", "SCHEDULED_ON"}.issubset(types):
            qc_issues.append(_qc_issue("$.working_annotation.relations", "contradictory_temporal_relation", f"{pair} is both DUE_ON and SCHEDULED_ON; verify intent"))

    for relation_id in sorted(_dependency_cycles(relations)):
        qc_issues.append(_qc_issue("$.working_annotation.relations", "dependency_cycle", f"dependency relation {relation_id!r} participates in a cycle", "ERROR"))

    for index, entity in enumerate(entities):
        if not isinstance(entity, dict) or entity.get("type") != "TASK":
            continue
        attributes = entity.get("task_attributes") or {}
        operation, status = attributes.get("operation"), attributes.get("status")
        if operation == "COMPLETE" and status == "CANCELED":
            qc_issues.append(_qc_issue(f"$.working_annotation.entities[{index}]", "operation_status_conflict", "COMPLETE conflicts with CANCELED status", "ERROR"))
        if operation == "CANCEL" and status == "COMPLETED":
            qc_issues.append(_qc_issue(f"$.working_annotation.entities[{index}]", "operation_status_conflict", "CANCEL conflicts with COMPLETED status", "ERROR"))

    schema_serialized = [{**asdict(issue), "severity": "ERROR"} for issue in schema_issues]
    all_issues = schema_serialized + qc_issues
    counts = Counter(issue["severity"] for issue in all_issues)
    return {
        "validated_at": utc_now(),
        "valid": counts["ERROR"] == 0,
        "error_count": counts["ERROR"],
        "warning_count": counts["WARNING"],
        "issues": all_issues,
    }


def _find_by_id(items: list[Any], identifier: str, kind: str) -> tuple[int, dict[str, Any]]:
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("id") == identifier:
            return index, item
    raise ValueError(f"Unknown {kind} ID: {identifier}")


def _record_event(document: dict[str, Any], reviewer_id: str, action: str, target_id: str | None, before: Any, after: Any) -> None:
    reviewer = document.setdefault("reviewer", {})
    if reviewer.get("started_at") is None:
        reviewer["started_at"] = utc_now()
    if reviewer.get("reviewer_id") not in {None, reviewer_id}:
        raise ValueError(f"Review is already assigned to {reviewer.get('reviewer_id')!r}")
    reviewer["reviewer_id"] = reviewer_id
    document.setdefault("correction_events", []).append({
        "timestamp": utc_now(),
        "reviewer_id": reviewer_id,
        "action": action,
        "target_id": target_id,
        "before": copy.deepcopy(before),
        "after": copy.deepcopy(after),
    })


def add_entity(document: dict[str, Any], reviewer_id: str, entity_id: str, entity_type: str, start: int, end: int) -> None:
    entity_type = entity_type.upper()
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"Unsupported entity type: {entity_type}")
    annotation = document["working_annotation"]
    entities = annotation["entities"]
    if any(isinstance(item, dict) and item.get("id") == entity_id for item in entities):
        raise ValueError(f"Duplicate entity ID: {entity_id}")
    text = document["source_record"].get("text", "")
    if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
        raise ValueError(f"Invalid character span [{start}, {end}) for text length {len(text)}")
    entity = {
        "id": entity_id,
        "type": entity_type,
        "start": start,
        "end": end,
        "text": text[start:end],
        "task_attributes": default_task_attributes() if entity_type == "TASK" else None,
    }
    entities.append(entity)
    _record_event(document, reviewer_id, "ADD_ENTITY", entity_id, None, entity)


def set_entity(
    document: dict[str, Any],
    reviewer_id: str,
    entity_id: str,
    *,
    entity_type: str | None = None,
    start: int | None = None,
    end: int | None = None,
) -> None:
    entities = document["working_annotation"]["entities"]
    _, entity = _find_by_id(entities, entity_id, "entity")
    before = copy.deepcopy(entity)
    if entity_type is not None:
        entity_type = entity_type.upper()
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Unsupported entity type: {entity_type}")
        old_type = entity.get("type")
        entity["type"] = entity_type
        if old_type != "TASK" and entity_type == "TASK":
            entity["task_attributes"] = default_task_attributes()
        elif old_type == "TASK" and entity_type != "TASK":
            entity["task_attributes"] = None
    new_start = entity.get("start") if start is None else start
    new_end = entity.get("end") if end is None else end
    text = document["source_record"].get("text", "")
    if not (isinstance(new_start, int) and isinstance(new_end, int) and 0 <= new_start < new_end <= len(text)):
        raise ValueError(f"Invalid character span [{new_start}, {new_end}) for text length {len(text)}")
    entity.update({"start": new_start, "end": new_end, "text": text[new_start:new_end]})
    _record_event(document, reviewer_id, "SET_ENTITY", entity_id, before, entity)


def delete_entity(document: dict[str, Any], reviewer_id: str, entity_id: str, *, cascade: bool = False) -> None:
    annotation = document["working_annotation"]
    index, entity = _find_by_id(annotation["entities"], entity_id, "entity")
    linked = [relation for relation in annotation["relations"] if relation.get("source_entity_id") == entity_id or relation.get("target_entity_id") == entity_id]
    if linked and not cascade:
        raise ValueError(f"Entity {entity_id} has {len(linked)} linked relation(s); pass cascade=True explicitly")
    if linked:
        annotation["relations"] = [relation for relation in annotation["relations"] if relation not in linked]
        _record_event(document, reviewer_id, "CASCADE_DELETE_RELATIONS", entity_id, linked, [])
    del annotation["entities"][index]
    _record_event(document, reviewer_id, "DELETE_ENTITY", entity_id, entity, None)


def set_task_attribute(document: dict[str, Any], reviewer_id: str, entity_id: str, key: str, value: Any) -> None:
    _, entity = _find_by_id(document["working_annotation"]["entities"], entity_id, "entity")
    if entity.get("type") != "TASK":
        raise ValueError(f"Entity {entity_id} is not a TASK")
    attributes = entity.get("task_attributes")
    if not isinstance(attributes, dict) or key not in attributes:
        raise ValueError(f"Unknown task attribute: {key}")
    before = copy.deepcopy(attributes.get(key))
    attributes[key] = value
    _record_event(document, reviewer_id, "SET_TASK_ATTRIBUTE", f"{entity_id}.{key}", before, value)


def add_relation(
    document: dict[str, Any],
    reviewer_id: str,
    relation_id: str,
    relation_type: str,
    source_id: str,
    target_id: str,
    evidence_start: int,
    evidence_end: int,
    *,
    explicit_vs_inferred: str = "EXPLICIT",
    ambiguous: bool = False,
) -> None:
    relation_type = relation_type.upper()
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"Unsupported stored relation type: {relation_type}")
    annotation = document["working_annotation"]
    if any(isinstance(item, dict) and item.get("id") == relation_id for item in annotation["relations"]):
        raise ValueError(f"Duplicate relation ID: {relation_id}")
    entity_ids = {entity.get("id") for entity in annotation["entities"] if isinstance(entity, dict)}
    if source_id not in entity_ids or target_id not in entity_ids:
        raise ValueError("Relation endpoints must reference existing entities")
    text = document["source_record"].get("text", "")
    if not (0 <= evidence_start < evidence_end <= len(text)):
        raise ValueError(f"Invalid evidence span [{evidence_start}, {evidence_end})")
    relation = {
        "id": relation_id,
        "type": relation_type,
        "source_entity_id": source_id,
        "target_entity_id": target_id,
        "relation_evidence": {
            "start": evidence_start,
            "end": evidence_end,
            "text": text[evidence_start:evidence_end],
        },
        "explicit_vs_inferred": explicit_vs_inferred.upper(),
        "ambiguous": ambiguous,
    }
    annotation["relations"].append(relation)
    _record_event(document, reviewer_id, "ADD_RELATION", relation_id, None, relation)


def set_relation(
    document: dict[str, Any],
    reviewer_id: str,
    relation_id: str,
    *,
    relation_type: str | None = None,
    source_id: str | None = None,
    target_id: str | None = None,
    evidence_start: int | None = None,
    evidence_end: int | None = None,
    explicit_vs_inferred: str | None = None,
    ambiguous: bool | None = None,
) -> None:
    annotation = document["working_annotation"]
    _, relation = _find_by_id(annotation["relations"], relation_id, "relation")
    before = copy.deepcopy(relation)
    if relation_type is not None:
        relation_type = relation_type.upper()
        if relation_type not in RELATION_TYPES:
            raise ValueError(f"Unsupported stored relation type: {relation_type}")
        relation["type"] = relation_type
    if source_id is not None:
        relation["source_entity_id"] = source_id
    if target_id is not None:
        relation["target_entity_id"] = target_id
    if explicit_vs_inferred is not None:
        relation["explicit_vs_inferred"] = explicit_vs_inferred.upper()
    if ambiguous is not None:
        relation["ambiguous"] = ambiguous
    if evidence_start is not None or evidence_end is not None:
        evidence = relation.get("relation_evidence") or {}
        start = evidence.get("start") if evidence_start is None else evidence_start
        end = evidence.get("end") if evidence_end is None else evidence_end
        text = document["source_record"].get("text", "")
        if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
            raise ValueError(f"Invalid evidence span [{start}, {end})")
        relation["relation_evidence"] = {"start": start, "end": end, "text": text[start:end]}
    _record_event(document, reviewer_id, "SET_RELATION", relation_id, before, relation)


def delete_relation(document: dict[str, Any], reviewer_id: str, relation_id: str) -> None:
    relations = document["working_annotation"]["relations"]
    index, relation = _find_by_id(relations, relation_id, "relation")
    del relations[index]
    _record_event(document, reviewer_id, "DELETE_RELATION", relation_id, relation, None)


def mark_review(
    document: dict[str, Any],
    reviewer_id: str,
    quality_tier: str,
    *,
    confirm_human: bool,
    acknowledge_warnings: bool = False,
    note: str | None = None,
) -> None:
    quality_tier = quality_tier.upper()
    if quality_tier not in QUALITY_TIERS:
        raise ValueError(f"Unsupported quality tier: {quality_tier}")
    if not confirm_human:
        raise ValueError("Human confirmation is required; automated validation alone cannot assign a quality tier")
    validation = validate_review_document(document)
    if quality_tier in {"GOLD", "SILVER"} and validation["error_count"]:
        raise ValueError(f"Cannot mark {quality_tier}: {validation['error_count']} validation error(s) remain")
    if quality_tier == "GOLD" and validation["warning_count"] and not acknowledge_warnings:
        raise ValueError("GOLD has unresolved warnings; explicitly acknowledge them after semantic review")
    before = {"quality_tier": document.get("quality_tier"), "review_status": document.get("review_status")}
    document["quality_tier"] = quality_tier
    document["review_status"] = "COMPLETED"
    reviewer = document.setdefault("reviewer", {})
    reviewer["reviewer_id"] = reviewer_id
    reviewer["started_at"] = reviewer.get("started_at") or utc_now()
    reviewer["completed_at"] = utc_now()
    if note:
        reviewer.setdefault("notes", []).append(note)
    if acknowledge_warnings:
        document["acknowledged_warnings"] = [issue["code"] for issue in validation["issues"] if issue["severity"] == "WARNING"]
    annotation = document.get("working_annotation")
    if isinstance(annotation, dict) and quality_tier in {"GOLD", "SILVER"}:
        annotation["annotation_status"] = "REVIEWED"
        annotation["annotator_id"] = reviewer_id
    _record_event(
        document,
        reviewer_id,
        "MARK_REVIEW",
        document.get("record_id"),
        before,
        {"quality_tier": quality_tier, "review_status": "COMPLETED"},
    )
    document["validation"] = validate_review_document(document)


def _annotation_differences(original: Mapping[str, Any] | None, final: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    if original is None:
        return [("prediction", "no_original_prediction")]
    if final is None:
        return [("prediction", "no_final_annotation")]
    differences: list[tuple[str, str]] = []
    original_entities = {e.get("id"): e for e in original.get("entities", []) if isinstance(e, dict)}
    final_entities = {e.get("id"): e for e in final.get("entities", []) if isinstance(e, dict)}
    for identifier in sorted(original_entities.keys() - final_entities.keys()):
        differences.append(("entity_deleted", str(original_entities[identifier].get("type"))))
    for identifier in sorted(final_entities.keys() - original_entities.keys()):
        differences.append(("entity_added", str(final_entities[identifier].get("type"))))
    for identifier in sorted(original_entities.keys() & final_entities.keys()):
        before, after = original_entities[identifier], final_entities[identifier]
        if before.get("type") != after.get("type"):
            differences.append(("entity_type", f"{before.get('type')}->{after.get('type')}"))
        if (before.get("start"), before.get("end")) != (after.get("start"), after.get("end")):
            differences.append(("entity_span", str(after.get("type"))))
        before_attrs, after_attrs = before.get("task_attributes") or {}, after.get("task_attributes") or {}
        for key in sorted(set(before_attrs) | set(after_attrs)):
            if before_attrs.get(key) != after_attrs.get(key):
                differences.append(("task_attribute", key))

    original_relations = {r.get("id"): r for r in original.get("relations", []) if isinstance(r, dict)}
    final_relations = {r.get("id"): r for r in final.get("relations", []) if isinstance(r, dict)}
    for identifier in sorted(original_relations.keys() - final_relations.keys()):
        differences.append(("relation_deleted", str(original_relations[identifier].get("type"))))
    for identifier in sorted(final_relations.keys() - original_relations.keys()):
        differences.append(("relation_added", str(final_relations[identifier].get("type"))))
    for identifier in sorted(original_relations.keys() & final_relations.keys()):
        before, after = original_relations[identifier], final_relations[identifier]
        if before.get("type") != after.get("type"):
            differences.append(("relation_type", f"{before.get('type')}->{after.get('type')}"))
        if (before.get("source_entity_id"), before.get("target_entity_id")) != (after.get("source_entity_id"), after.get("target_entity_id")):
            differences.append(("relation_link", str(after.get("type"))))
        if before.get("relation_evidence") != after.get("relation_evidence"):
            differences.append(("relation_evidence", str(after.get("type"))))
    return differences


def iter_review_documents(root: Path | str) -> Iterable[tuple[Path, dict[str, Any]]]:
    for path in sorted(Path(root).rglob("*.review.json")):
        yield path, load_review(path)


def build_quality_outputs(review_root: Path | str, report_path: Path | str, csv_path: Path | str) -> dict[str, int]:
    documents = [document for _, document in iter_review_documents(review_root)]
    pending = Counter(document.get("source_split") for document in documents if document.get("review_status") != "COMPLETED")
    completed = [document for document in documents if document.get("review_status") == "COMPLETED"]
    decisions = Counter((document.get("source_split"), document.get("quality_tier")) for document in completed)
    corrections: Counter[tuple[str, bool, str, str]] = Counter()
    issue_counts: Counter[tuple[str, bool, str]] = Counter()
    for document in completed:
        split = str(document.get("source_split"))
        eligible = bool(document.get("prompt_feedback_eligible"))
        for category, label in _annotation_differences(document.get("original_prediction"), document.get("working_annotation")):
            corrections[(split, eligible, category, label)] += 1
        for issue in document.get("validation", {}).get("issues", []):
            issue_counts[(split, eligible, str(issue.get("code")))] += 1

    rows: list[dict[str, Any]] = []
    for (split, eligible, category, label), count in sorted(corrections.items()):
        total = sum(1 for document in completed if document.get("source_split") == split)
        rows.append({
            "source_split": split,
            "prompt_feedback_eligible": str(eligible).lower(),
            "metric": "correction",
            "category": category,
            "label": label,
            "count": count,
            "reviewed_records": total,
            "rate": f"{count / total:.6f}" if total else "0.000000",
        })
    for (split, eligible, code), count in sorted(issue_counts.items()):
        total = sum(1 for document in completed if document.get("source_split") == split)
        rows.append({
            "source_split": split,
            "prompt_feedback_eligible": str(eligible).lower(),
            "metric": "remaining_issue",
            "category": "validation",
            "label": code,
            "count": count,
            "reviewed_records": total,
            "rate": f"{count / total:.6f}" if total else "0.000000",
        })

    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_csv = csv_path.with_suffix(csv_path.suffix + ".tmp")
    fieldnames = ["source_split", "prompt_feedback_eligible", "metric", "category", "label", "count", "reviewed_records", "rate"]
    with temporary_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary_csv.replace(csv_path)

    lines = [
        "# Text2Task annotation quality report",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Review status",
        "",
        f"- Prepared review records: {len(documents)}",
        f"- Human-completed reviews: {len(completed)}",
        f"- Pending reviews: {len(documents) - len(completed)}",
    ]
    for split in ("train", "dev", "test"):
        split_total = sum(1 for document in documents if document.get("source_split") == split)
        split_completed = sum(1 for document in completed if document.get("source_split") == split)
        lines.append(f"- {split}: {split_completed} completed / {split_total} prepared ({pending.get(split, 0)} pending)")
    lines.extend([
        "",
        "## Human decisions",
        "",
    ])
    if decisions:
        for (split, tier), count in sorted(decisions.items()):
            lines.append(f"- {split} / {tier}: {count}")
    else:
        lines.append("No records have been human-verified yet. Automated validation never assigns GOLD.")
    lines.extend([
        "",
        "## Frequent corrections",
        "",
    ])
    eligible_corrections = [item for item in corrections.items() if item[0][1]]
    if eligible_corrections:
        for (split, _eligible, category, label), count in sorted(eligible_corrections, key=lambda item: (-item[1], item[0]))[:20]:
            lines.append(f"- {split}: {category} / {label}: {count}")
    else:
        lines.append("No eligible human correction statistics are available yet.")
    lines.extend([
        "",
        "## Reviewer workflow",
        "",
        "1. List pending items with `python3 scripts/review_annotations.py list --split dev`.",
        "2. Inspect one record with `python3 scripts/review_annotations.py show REVIEW_FILE`. Dev/test predictions remain hidden during independent annotation.",
        "3. Add or correct spans, types, task attributes, and relations using the `add-*`, `set-*`, and `delete-*` subcommands. Every tool-driven change is appended to `correction_events`.",
        "4. Run `python3 scripts/review_annotations.py validate REVIEW_FILE`. Resolve errors; explicitly inspect every dependency warning. Ambiguity may remain encoded through `ambiguous`, `UNKNOWN`, and `unresolved_fields`.",
        "5. After actual inspection, use `mark --tier GOLD|SILVER|REJECTED --reviewer REVIEWER_ID --confirm-human`. GOLD warnings require `--acknowledge-warnings`.",
        "6. Run `python3 scripts/review_annotations.py finalize` to export decisions and refresh quality statistics.",
        "",
        "## Test-set isolation",
        "",
        "Test reviews are always marked `prompt_feedback_eligible=false`. Their corrections are retained for final quality assessment but must not be used to modify prompts, choose models, or select training configurations.",
        "",
        "## Quality-control policy",
        "",
        "- Dev and test records default to blind independent annotation; predictions remain hidden until explicit reveal or completion.",
        "- GOLD and SILVER require an explicit human confirmation flag and reviewer identity.",
        "- Invalid offsets, schema failures, unsupported evidence, dependency cycles, and operation/status conflicts are surfaced by validation.",
        "- Every DEPENDS_ON edge receives a semantic-review warning even when structurally valid.",
        "- Original LLM predictions and their hashes remain stored separately from reviewer corrections.",
        "",
        "Detailed machine-readable counts are in `data/reports/correction_statistics.csv`.",
        "",
    ])
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_report.write_text("\n".join(lines), encoding="utf-8")
    temporary_report.replace(report_path)
    return {
        "prepared": len(documents),
        "completed": len(completed),
        "pending": len(documents) - len(completed),
        "correction_rows": len(rows),
    }


def finalize_reviews(
    review_root: Path | str,
    gold_dir: Path | str,
    silver_dir: Path | str,
    rejected_dir: Path | str,
) -> dict[str, int]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for _path, document in iter_review_documents(review_root):
        if document.get("review_status") != "COMPLETED":
            counts["pending_skipped"] += 1
            continue
        tier = str(document.get("quality_tier"))
        split = str(document.get("source_split"))
        reviewer = document.get("reviewer") or {}
        if tier not in QUALITY_TIERS or not reviewer.get("reviewer_id") or not reviewer.get("completed_at"):
            counts["invalid_review_skipped"] += 1
            continue
        validation = validate_review_document(document)
        if tier in {"GOLD", "SILVER"} and validation["error_count"]:
            counts["invalid_review_skipped"] += 1
            continue
        output = copy.deepcopy(document["source_record"])
        output["llm_prediction_original"] = copy.deepcopy(document.get("original_prediction"))
        output["llm_prediction_metadata"] = copy.deepcopy(document.get("original_prediction_metadata"))
        output["text2task_annotations"] = copy.deepcopy(document.get("working_annotation")) if tier != "REJECTED" else None
        output["human_review"] = {
            "review_schema_version": REVIEW_SCHEMA_VERSION,
            "review_mode": document.get("review_mode"),
            "review_status": document.get("review_status"),
            "quality_tier": tier,
            "reviewer": copy.deepcopy(reviewer),
            "prompt_feedback_eligible": document.get("prompt_feedback_eligible"),
            "source_record_hash": document.get("source_record_hash"),
            "original_prediction_hash": document.get("original_prediction_hash"),
            "correction_events": copy.deepcopy(document.get("correction_events", [])),
            "acknowledged_warnings": copy.deepcopy(document.get("acknowledged_warnings", [])),
            "validation": validation,
        }
        grouped[(tier, split)].append(output)
        counts[f"exported_{tier.lower()}"] += 1

    roots = {"GOLD": Path(gold_dir), "SILVER": Path(silver_dir), "REJECTED": Path(rejected_dir)}
    for tier, root in roots.items():
        root.mkdir(parents=True, exist_ok=True)
        for split in ("train", "dev", "test"):
            values = sorted(grouped.get((tier, split), []), key=lambda item: (item.get("thread_id", ""), item.get("turn_index", 0), item.get("id", "")))
            atomic_jsonl(root / f"{split}.jsonl", values)
    return dict(counts)


def render_review(document: Mapping[str, Any], *, reveal_prediction: bool = False) -> str:
    source = document.get("source_record") or {}
    text = str(source.get("text", ""))
    lines = [
        f"Record: {document.get('record_id')}  split={document.get('source_split')}",
        f"Mode: {document.get('review_mode')}  status={document.get('review_status')}  tier={document.get('quality_tier')}",
        f"Prompt-feedback eligible: {document.get('prompt_feedback_eligible')}",
        "",
        "ORIGINAL EMAIL TEXT",
        text,
        "",
    ]

    def render_annotation(title: str, annotation: Any) -> None:
        lines.append(title)
        if not isinstance(annotation, dict):
            lines.append("  [none]")
            lines.append("")
            return
        lines.append("  Entities:")
        for entity in annotation.get("entities", []):
            if not isinstance(entity, dict):
                continue
            start, end, surface = entity.get("start"), entity.get("end"), entity.get("text")
            valid = isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text) and text[start:end] == surface
            marker = "OK" if valid else "INVALID OFFSET"
            lines.append(f"    {entity.get('id')} {entity.get('type')} [{start},{end}) {surface!r}  <{marker}>")
            if entity.get("type") == "TASK":
                lines.append(f"      attributes={json.dumps(entity.get('task_attributes'), ensure_ascii=False, sort_keys=True)}")
        lines.append("  Relations:")
        for relation in annotation.get("relations", []):
            if not isinstance(relation, dict):
                continue
            evidence = relation.get("relation_evidence") or {}
            dependency = "  <SEMANTIC REVIEW REQUIRED>" if relation.get("type") == "DEPENDS_ON" else ""
            lines.append(
                f"    {relation.get('id')} {relation.get('source_entity_id')} -{relation.get('type')}-> "
                f"{relation.get('target_entity_id')} evidence=[{evidence.get('start')},{evidence.get('end')}) "
                f"{evidence.get('text')!r}{dependency}"
            )
        lines.append("")

    independent_pending = document.get("review_mode") == "INDEPENDENT" and document.get("review_status") != "COMPLETED"
    if independent_pending and not reveal_prediction:
        lines.extend(["ORIGINAL LLM PREDICTION", "  [hidden during independent review; use --reveal-prediction only after committing your annotation]", ""])
    else:
        render_annotation("ORIGINAL LLM PREDICTION", document.get("original_prediction"))
    render_annotation("WORKING HUMAN ANNOTATION", document.get("working_annotation"))
    failure = document.get("original_failure")
    if failure and (not independent_pending or reveal_prediction):
        failure_body = failure.get("failure", failure) if isinstance(failure, dict) else failure
        lines.extend(["ORIGINAL LLM FAILURE", f"  {json.dumps(failure_body, ensure_ascii=False)[:2000]}", ""])
    validation = validate_review_document(document)
    lines.append(f"VALIDATION: valid={validation['valid']} errors={validation['error_count']} warnings={validation['warning_count']}")
    for issue in validation["issues"]:
        lines.append(f"  [{issue['severity']}] {issue['code']} {issue['path']}: {issue['message']}")
    return "\n".join(lines)
