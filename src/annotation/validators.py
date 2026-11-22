"""Dependency-free validation for Text2Task annotation records.

The JSON file is a standard Draft 2020-12 schema.  This module implements the
small schema vocabulary used by that file and then applies graph and span
constraints that JSON Schema alone cannot express cleanly (exact substring
matching, relation endpoint types, ID uniqueness, and missing-field markers).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "configs" / "text2task_schema_v1.json"

ENTITY_TYPES = {"TASK", "PERSON", "GROUP", "TEMPORAL", "EVENT", "ARTIFACT"}
STORED_RELATIONS = {"ASSIGNED_TO", "DUE_ON", "SCHEDULED_ON", "DEPENDS_ON"}
CANDIDATE_RELATIONS = STORED_RELATIONS | {"NONE"}
ENDPOINT_TYPES = {
    "ASSIGNED_TO": ({"TASK"}, {"PERSON", "GROUP"}),
    "DUE_ON": ({"TASK"}, {"TEMPORAL"}),
    "SCHEDULED_ON": ({"TASK"}, {"TEMPORAL"}),
    "DEPENDS_ON": ({"TASK"}, {"TASK", "EVENT"}),
}


@dataclass(frozen=True)
class ValidationIssue:
    """One machine-readable validation failure."""

    path: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.code}] {self.message}"


def load_schema(path: Path | str = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    """Load the canonical JSON schema."""

    schema_path = Path(path)
    with schema_path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError(f"Schema root must be an object: {schema_path}")
    return schema


def _join(path: str, component: str | int) -> str:
    return f"{path}[{component}]" if isinstance(component, int) else f"{path}.{component}"


def _resolve_ref(root: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"Only local JSON pointers are supported: {reference}")
    value: Any = root
    for raw_component in reference[2:].split("/"):
        component = raw_component.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping) or component not in value:
            raise ValueError(f"Unresolvable JSON Schema reference: {reference}")
        value = value[component]
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON Schema reference does not resolve to an object: {reference}")
    return value


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }.get(expected, lambda: False)()


def _schema_issues(
    value: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
) -> list[ValidationIssue]:
    """Evaluate the JSON Schema vocabulary used by the v1 schema."""

    if "$ref" in schema:
        try:
            target = _resolve_ref(root, schema["$ref"])
        except ValueError as error:
            return [ValidationIssue(path, "schema_ref", str(error))]
        return _schema_issues(value, target, root, path)

    if "anyOf" in schema:
        alternatives = [_schema_issues(value, option, root, path) for option in schema["anyOf"]]
        if not any(not issues for issues in alternatives):
            return [ValidationIssue(path, "any_of", "value does not match any permitted schema alternative")]
        return []

    issues: list[ValidationIssue] = []
    expected_type = schema.get("type")
    if expected_type is not None:
        expected = [expected_type] if isinstance(expected_type, str) else expected_type
        if not isinstance(expected, list) or not any(_matches_type(value, item) for item in expected):
            return [ValidationIssue(path, "type", f"expected {expected_type!r}, got {type(value).__name__}")]

    if "const" in schema and value != schema["const"]:
        issues.append(ValidationIssue(path, "const", f"expected constant {schema['const']!r}"))
    if "enum" in schema and value not in schema["enum"]:
        issues.append(ValidationIssue(path, "enum", f"unexpected value {value!r}"))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            issues.append(ValidationIssue(path, "min_length", "string is shorter than permitted"))
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            issues.append(ValidationIssue(path, "pattern", f"does not match {schema['pattern']!r}"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            issues.append(ValidationIssue(path, "minimum", f"must be at least {schema['minimum']}"))

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            issues.append(ValidationIssue(path, "min_items", "array has too few items"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            issues.append(ValidationIssue(path, "max_items", "array has too many items"))
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(encoded) != len(set(encoded)):
                issues.append(ValidationIssue(path, "unique_items", "array items must be unique"))
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                issues.extend(_schema_issues(item, item_schema, root, _join(path, index)))

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                issues.append(ValidationIssue(_join(path, key), "required", "required property is missing"))
        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value:
                issues.extend(_schema_issues(value[key], child_schema, root, _join(path, key)))
        extras = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for key in sorted(extras):
                issues.append(ValidationIssue(_join(path, key), "additional_property", "property is not allowed"))
        elif isinstance(additional, Mapping):
            for key in sorted(extras):
                issues.extend(_schema_issues(value[key], additional, root, _join(path, key)))
    return issues


def _all_refs(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        if isinstance(value.get("$ref"), str):
            yield value["$ref"]
        for child in value.values():
            yield from _all_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_refs(child)


def validate_schema_definition(schema: Mapping[str, Any] | None = None) -> list[ValidationIssue]:
    """Check schema integrity and the v1 label-policy contract."""

    schema = schema or load_schema()
    issues: list[ValidationIssue] = []
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        issues.append(ValidationIssue("$.$schema", "schema_draft", "Draft 2020-12 must be declared"))
    for reference in _all_refs(schema):
        try:
            _resolve_ref(schema, reference)
        except ValueError as error:
            issues.append(ValidationIssue("$", "schema_ref", str(error)))

    policy = schema.get("x-text2task-label-policy", {})
    expected_policy = {
        "entity_labels": ENTITY_TYPES,
        "stored_relation_labels": STORED_RELATIONS,
        "candidate_relation_labels": CANDIDATE_RELATIONS,
        "deferred_relation_labels": {"REFERS_TO"},
    }
    for key, expected in expected_policy.items():
        actual = policy.get(key)
        if not isinstance(actual, list) or set(actual) != expected or len(actual) != len(expected):
            issues.append(ValidationIssue(f"$.x-text2task-label-policy.{key}", "label_policy", f"expected {sorted(expected)}"))
    if "NONE" in set(policy.get("stored_relation_labels", [])):
        issues.append(ValidationIssue("$.x-text2task-label-policy", "none_edge", "NONE cannot be a stored edge"))
    if "REFERS_TO" in set(policy.get("stored_relation_labels", [])) | set(policy.get("candidate_relation_labels", [])):
        issues.append(ValidationIssue("$.x-text2task-label-policy", "reference_deferred", "REFERS_TO must remain deferred in v1"))
    return issues


def _validate_exact_span(
    text: str,
    span: Mapping[str, Any],
    path: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    start, end, surface = span.get("start"), span.get("end"), span.get("text")
    if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
        return issues
    if start < 0 or end <= start or end > len(text):
        issues.append(ValidationIssue(path, "span_bounds", f"span [{start}, {end}) is invalid for text length {len(text)}"))
    elif isinstance(surface, str) and text[start:end] != surface:
        issues.append(ValidationIssue(_join(path, "text"), "span_text", f"expected exact substring {text[start:end]!r}"))
    return issues


def _endpoint_issue(
    relation_type: str,
    source_type: str | None,
    target_type: str | None,
    path: str,
) -> list[ValidationIssue]:
    if relation_type not in ENDPOINT_TYPES:
        return []
    permitted_source, permitted_target = ENDPOINT_TYPES[relation_type]
    issues = []
    if source_type not in permitted_source:
        issues.append(ValidationIssue(_join(path, "source_entity_id"), "source_type", f"{relation_type} source must be {sorted(permitted_source)}"))
    if target_type not in permitted_target:
        issues.append(ValidationIssue(_join(path, "target_entity_id"), "target_type", f"{relation_type} target must be {sorted(permitted_target)}"))
    return issues


def validate_record(
    record: Any,
    schema: Mapping[str, Any] | None = None,
    *,
    require_annotations: bool = False,
) -> list[ValidationIssue]:
    """Validate one email record against JSON and semantic graph constraints."""

    schema = schema or load_schema()
    issues = _schema_issues(record, schema, schema, "$")
    if not isinstance(record, dict):
        return issues
    annotations = record.get("text2task_annotations")
    if annotations is None:
        if require_annotations:
            issues.append(ValidationIssue("$.text2task_annotations", "annotations_required", "annotation set is null"))
        return issues
    if not isinstance(annotations, dict):
        return issues
    text = record.get("text")
    if not isinstance(text, str):
        return issues

    if annotations.get("annotation_status") in {"REVIEWED", "ADJUDICATED"} and not annotations.get("annotator_id"):
        issues.append(ValidationIssue("$.text2task_annotations.annotator_id", "annotator_required", "reviewed/adjudicated annotations require an annotator ID"))

    entities = annotations.get("entities")
    if not isinstance(entities, list):
        return issues
    entity_by_id: dict[str, Mapping[str, Any]] = {}
    entity_spans: set[tuple[Any, Any, Any]] = set()
    for index, entity in enumerate(entities):
        path = f"$.text2task_annotations.entities[{index}]"
        if not isinstance(entity, dict):
            continue
        entity_id = entity.get("id")
        if isinstance(entity_id, str):
            if entity_id in entity_by_id:
                issues.append(ValidationIssue(_join(path, "id"), "duplicate_id", f"duplicate entity ID {entity_id!r}"))
            else:
                entity_by_id[entity_id] = entity
        issues.extend(_validate_exact_span(text, entity, path))
        signature = (entity.get("type"), entity.get("start"), entity.get("end"))
        if signature in entity_spans:
            issues.append(ValidationIssue(path, "duplicate_entity", "same type and span already exist"))
        entity_spans.add(signature)
        attributes = entity.get("task_attributes")
        if entity.get("type") == "TASK":
            if not isinstance(attributes, dict):
                issues.append(ValidationIssue(_join(path, "task_attributes"), "task_attributes", "TASK requires task attributes"))
                continue
            required_task_attributes = {
                "operation",
                "status",
                "negated",
                "ambiguous",
                "missing_fields",
                "unresolved_fields",
                "thread_task_id",
                "identity_status",
            }
            for field_name in sorted(required_task_attributes - set(attributes)):
                issues.append(
                    ValidationIssue(
                        _join(_join(path, "task_attributes"), field_name),
                        "required",
                        "required task attribute is missing",
                    )
                )
            missing = set(attributes.get("missing_fields", [])) if isinstance(attributes.get("missing_fields"), list) else set()
            unresolved = set(attributes.get("unresolved_fields", [])) if isinstance(attributes.get("unresolved_fields"), list) else set()
            if unresolved and attributes.get("ambiguous") is not True:
                issues.append(ValidationIssue(_join(path, "ambiguous"), "unresolved_ambiguity", "unresolved fields require ambiguous=true"))
            if attributes.get("operation") == "UNKNOWN" and "OPERATION" not in unresolved:
                issues.append(ValidationIssue(_join(path, "unresolved_fields"), "unknown_operation", "UNKNOWN operation must be marked unresolved"))
            if attributes.get("status") == "UNKNOWN" and "STATUS" not in unresolved:
                issues.append(ValidationIssue(_join(path, "unresolved_fields"), "unknown_status", "UNKNOWN status must be marked unresolved"))
            identity = attributes.get("identity_status")
            thread_task_id = attributes.get("thread_task_id")
            if identity == "RESOLVED" and not isinstance(thread_task_id, str):
                issues.append(ValidationIssue(_join(path, "thread_task_id"), "resolved_identity", "resolved identity requires thread_task_id"))
            if identity != "RESOLVED" and thread_task_id is not None:
                issues.append(ValidationIssue(_join(path, "thread_task_id"), "unresolved_identity", "only resolved identity may have thread_task_id"))
            if identity == "UNRESOLVED" and "CROSS_EMAIL_IDENTITY" not in unresolved:
                issues.append(ValidationIssue(_join(path, "unresolved_fields"), "identity_marker", "unresolved identity must be marked CROSS_EMAIL_IDENTITY"))
            if identity != "UNRESOLVED" and "CROSS_EMAIL_IDENTITY" in unresolved:
                issues.append(ValidationIssue(_join(path, "unresolved_fields"), "identity_marker", "CROSS_EMAIL_IDENTITY requires identity_status=UNRESOLVED"))
            if missing & unresolved:
                issues.append(ValidationIssue(_join(path, "unresolved_fields"), "missing_unresolved_conflict", "a field cannot be both missing and unresolved"))
        elif attributes is not None:
            issues.append(ValidationIssue(_join(path, "task_attributes"), "non_task_attributes", "only TASK entities may have task attributes"))

    relations = annotations.get("relations")
    relations = relations if isinstance(relations, list) else []
    relation_ids: set[str] = set()
    relation_edges: set[tuple[Any, Any, Any]] = set()
    task_relation_types: dict[str, set[str]] = {}
    for index, relation in enumerate(relations):
        path = f"$.text2task_annotations.relations[{index}]"
        if not isinstance(relation, dict):
            continue
        relation_id = relation.get("id")
        if isinstance(relation_id, str):
            if relation_id in relation_ids:
                issues.append(ValidationIssue(_join(path, "id"), "duplicate_id", f"duplicate relation ID {relation_id!r}"))
            relation_ids.add(relation_id)
        relation_type = relation.get("type")
        if relation_type in {"NONE", "REFERS_TO"}:
            issues.append(ValidationIssue(_join(path, "type"), "non_edge_label", f"{relation_type} cannot be stored as a v1 graph edge"))
        source_id, target_id = relation.get("source_entity_id"), relation.get("target_entity_id")
        if source_id == target_id and isinstance(source_id, str):
            issues.append(ValidationIssue(path, "self_relation", "a relation cannot point to the same entity"))
        source = entity_by_id.get(source_id) if isinstance(source_id, str) else None
        target = entity_by_id.get(target_id) if isinstance(target_id, str) else None
        if source is None:
            issues.append(ValidationIssue(_join(path, "source_entity_id"), "unknown_entity", f"unknown entity ID {source_id!r}"))
        if target is None:
            issues.append(ValidationIssue(_join(path, "target_entity_id"), "unknown_entity", f"unknown entity ID {target_id!r}"))
        if isinstance(relation_type, str):
            issues.extend(_endpoint_issue(relation_type, source.get("type") if source else None, target.get("type") if target else None, path))
            if isinstance(source_id, str):
                task_relation_types.setdefault(source_id, set()).add(relation_type)
        edge = (relation_type, source_id, target_id)
        if edge in relation_edges:
            issues.append(ValidationIssue(path, "duplicate_relation", "same typed relation edge already exists"))
        relation_edges.add(edge)
        evidence = relation.get("relation_evidence")
        if isinstance(evidence, dict):
            issues.extend(_validate_exact_span(text, evidence, _join(path, "relation_evidence")))

    candidates = annotations.get("relation_candidates")
    candidates = candidates if isinstance(candidates, list) else []
    candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        path = f"$.text2task_annotations.relation_candidates[{index}]"
        if not isinstance(candidate, dict):
            continue
        candidate_id = candidate.get("id")
        if isinstance(candidate_id, str):
            if candidate_id in candidate_ids:
                issues.append(ValidationIssue(_join(path, "id"), "duplicate_id", f"duplicate candidate ID {candidate_id!r}"))
            candidate_ids.add(candidate_id)
        source_id, target_id = candidate.get("source_entity_id"), candidate.get("target_entity_id")
        source = entity_by_id.get(source_id) if isinstance(source_id, str) else None
        target = entity_by_id.get(target_id) if isinstance(target_id, str) else None
        if source is None:
            issues.append(ValidationIssue(_join(path, "source_entity_id"), "unknown_entity", f"unknown entity ID {source_id!r}"))
        if target is None:
            issues.append(ValidationIssue(_join(path, "target_entity_id"), "unknown_entity", f"unknown entity ID {target_id!r}"))
        label = candidate.get("label")
        if label == "NONE":
            if candidate.get("relation_evidence") is not None or candidate.get("explicit_vs_inferred") is not None:
                issues.append(ValidationIssue(path, "none_candidate_metadata", "NONE candidates must have null evidence and explicitness"))
        elif isinstance(label, str):
            issues.extend(_endpoint_issue(label, source.get("type") if source else None, target.get("type") if target else None, path))
            if not isinstance(candidate.get("relation_evidence"), dict) or candidate.get("explicit_vs_inferred") not in {"EXPLICIT", "INFERRED"}:
                issues.append(ValidationIssue(path, "positive_candidate_metadata", "positive candidates require evidence and explicitness"))
        evidence = candidate.get("relation_evidence")
        if isinstance(evidence, dict):
            issues.extend(_validate_exact_span(text, evidence, _join(path, "relation_evidence")))

    for entity_id, entity in entity_by_id.items():
        if entity.get("type") != "TASK" or not isinstance(entity.get("task_attributes"), dict):
            continue
        attributes = entity["task_attributes"]
        missing = set(attributes.get("missing_fields", []))
        unresolved = set(attributes.get("unresolved_fields", []))
        related = task_relation_types.get(entity_id, set())
        has_assignee = "ASSIGNED_TO" in related
        has_temporal = bool({"DUE_ON", "SCHEDULED_ON"} & related)
        if has_assignee and ("ASSIGNEE" in missing or "ASSIGNEE" in unresolved):
            issues.append(ValidationIssue(f"$.text2task_annotations.entities[{entities.index(entity)}].task_attributes", "assignee_marker_conflict", "assignee relation conflicts with missing/unresolved marker"))
        if not has_assignee and not ({"ASSIGNEE"} & (missing | unresolved)):
            issues.append(ValidationIssue(f"$.text2task_annotations.entities[{entities.index(entity)}].task_attributes", "assignee_marker_missing", "task without ASSIGNED_TO must mark ASSIGNEE missing or unresolved"))
        if has_temporal and ("TEMPORAL" in missing or "TEMPORAL" in unresolved):
            issues.append(ValidationIssue(f"$.text2task_annotations.entities[{entities.index(entity)}].task_attributes", "temporal_marker_conflict", "temporal relation conflicts with missing/unresolved marker"))
        if not has_temporal and not ({"TEMPORAL"} & (missing | unresolved)):
            issues.append(ValidationIssue(f"$.text2task_annotations.entities[{entities.index(entity)}].task_attributes", "temporal_marker_missing", "task without DUE_ON/SCHEDULED_ON must mark TEMPORAL missing or unresolved"))
    return issues


def validate_jsonl(
    path: Path | str,
    schema: Mapping[str, Any] | None = None,
    *,
    require_annotations: bool = False,
) -> list[ValidationIssue]:
    """Validate every non-empty JSON line, retaining line numbers in paths."""

    schema = schema or load_schema()
    issues: list[ValidationIssue] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                issues.append(ValidationIssue(f"line[{line_number}]", "blank_line", "blank JSONL lines are not allowed"))
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                issues.append(ValidationIssue(f"line[{line_number}]", "invalid_json", str(error)))
                continue
            for issue in validate_record(record, schema, require_annotations=require_annotations):
                issues.append(ValidationIssue(f"line[{line_number}]{issue.path[1:]}", issue.code, issue.message))
    return issues


def _raise_if_issues(issues: Sequence[ValidationIssue], context: str) -> None:
    if not issues:
        return
    preview = "\n".join(str(issue) for issue in issues[:20])
    remainder = f"\n... and {len(issues) - 20} more" if len(issues) > 20 else ""
    raise ValueError(f"{context} failed with {len(issues)} validation issue(s):\n{preview}{remainder}")


def assert_valid_record(
    record: Any,
    schema: Mapping[str, Any] | None = None,
    *,
    require_annotations: bool = False,
) -> None:
    _raise_if_issues(validate_record(record, schema, require_annotations=require_annotations), "Record validation")


def assert_valid_jsonl(
    path: Path | str,
    schema: Mapping[str, Any] | None = None,
    *,
    require_annotations: bool = False,
) -> None:
    _raise_if_issues(validate_jsonl(path, schema, require_annotations=require_annotations), f"JSONL validation for {path}")
