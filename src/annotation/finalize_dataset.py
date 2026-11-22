"""Leak-aware assembly of Text2Task experiment datasets.

The finalizer is intentionally conservative:

* source split and thread membership can never be changed;
* raw LLM silver is permitted only in training;
* validation and test require genuinely human-verified annotations;
* invalid, rejected, duplicated, or unverifiable records are quarantined;
* an empty but honest NOT_READY dataset is preferable to fabricated examples.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.annotation.validators import ENTITY_TYPES, STORED_RELATIONS, validate_record


SOURCE_TO_FINAL = {"train": "train", "dev": "validation", "test": "test"}
FINAL_TO_SOURCE = {value: key for key, value in SOURCE_TO_FINAL.items()}
SPLIT_PRIORITY = {"train": 0, "validation": 1, "test": 2}
EXPECTED_ENTITY_LABELS = sorted(ENTITY_TYPES)
EXPECTED_RELATION_LABELS = sorted(STORED_RELATIONS)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    path = Path(path)
    if not path.is_file():
        return values
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected object at {path}:{line_number}")
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
    temporary.replace(path)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def exact_text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", normalize_text(text), flags=re.UNICODE)


def _shingles(text: str) -> set[str]:
    tokens = _tokens(text)
    if len(tokens) < 3:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[index:index + 3]) for index in range(len(tokens) - 2)}


def _simhash(shingles: set[str]) -> int:
    if not shingles:
        return 0
    weights = [0] * 64
    for shingle in shingles:
        digest = int.from_bytes(hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if digest & (1 << bit) else -1
    return sum((1 << bit) for bit, weight in enumerate(weights) if weight >= 0)


def duplicate_audit(records_by_split: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Find exact and high-confidence near duplicates across different splits."""

    records: list[tuple[str, Mapping[str, Any], str, set[str], int]] = []
    exact_groups: dict[str, list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    for split, split_records in records_by_split.items():
        for record in split_records:
            text = str(record.get("text", ""))
            normalized = normalize_text(text)
            exact_groups[hashlib.sha256(normalized.encode("utf-8")).hexdigest()].append((split, record))
            shingles = _shingles(text)
            records.append((split, record, normalized, shingles, _simhash(shingles)))

    exact = []
    exact_pairs: set[tuple[str, str]] = set()
    for digest, members in exact_groups.items():
        splits = {split for split, _ in members}
        if len(splits) < 2:
            continue
        ids = sorted(str(record.get("id")) for _, record in members)
        exact.append({"sha256": digest, "splits": sorted(splits), "record_ids": ids})
        for left in ids:
            for right in ids:
                if left < right:
                    exact_pairs.add((left, right))

    # Eight 8-bit bands guarantee that hashes within Hamming distance <= 7
    # share at least one band, avoiding an O(n^2) scan of the cleaned corpus.
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    candidates: set[tuple[int, int]] = set()
    for index, (split, _record, normalized, _shingles_value, signature) in enumerate(records):
        if len(normalized) < 20:
            continue
        for band in range(8):
            key = (band, (signature >> (band * 8)) & 0xFF)
            for prior in buckets[key]:
                if records[prior][0] != split:
                    candidates.add((prior, index))
            buckets[key].append(index)

    near = []
    for left_index, right_index in sorted(candidates):
        left_split, left, left_text, left_shingles, left_hash = records[left_index]
        right_split, right, right_text, right_shingles, right_hash = records[right_index]
        left_id, right_id = str(left.get("id")), str(right.get("id"))
        if tuple(sorted((left_id, right_id))) in exact_pairs or left_text == right_text:
            continue
        if (left_hash ^ right_hash).bit_count() > 7:
            continue
        union = left_shingles | right_shingles
        jaccard = len(left_shingles & right_shingles) / len(union) if union else 0.0
        length_ratio = min(len(left_text), len(right_text)) / max(len(left_text), len(right_text))
        if jaccard < 0.85 or length_ratio < 0.8:
            continue
        sequence_ratio = SequenceMatcher(None, left_text, right_text, autojunk=False).ratio()
        if sequence_ratio < 0.92:
            continue
        near.append({
            "left_id": left_id,
            "left_split": left_split,
            "right_id": right_id,
            "right_split": right_split,
            "shingle_jaccard": round(jaccard, 6),
            "sequence_ratio": round(sequence_ratio, 6),
        })
    return {
        "exact_cross_split_groups": exact,
        "near_cross_split_pairs": near,
        "records_scanned": len(records),
        "near_candidate_pairs_compared": len(candidates),
    }


@dataclass
class SplitStats:
    threads: int = 0
    emails: int = 0
    tasks: int = 0
    entity_spans: int = 0
    relation_instances: int = 0
    dependency_links: int = 0
    multiple_task_messages: int = 0
    gold_records: int = 0
    silver_records: int = 0
    entity_labels: Counter[str] = field(default_factory=Counter)
    relation_labels: Counter[str] = field(default_factory=Counter)
    task_operations: Counter[str] = field(default_factory=Counter)
    task_statuses: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("entity_labels", "relation_labels", "task_operations", "task_statuses"):
            value[key] = dict(sorted(getattr(self, key).items()))
        return value


def summarize_split(records: Sequence[Mapping[str, Any]]) -> SplitStats:
    stats = SplitStats()
    stats.emails = len(records)
    stats.threads = len({record.get("thread_id") for record in records})
    for record in records:
        tier = (record.get("annotation_provenance") or {}).get("quality_tier")
        if tier == "GOLD":
            stats.gold_records += 1
        elif tier == "SILVER":
            stats.silver_records += 1
        annotations = record.get("text2task_annotations") or {}
        entities = annotations.get("entities", [])
        relations = annotations.get("relations", [])
        tasks = [entity for entity in entities if entity.get("type") == "TASK"]
        stats.tasks += len(tasks)
        stats.entity_spans += len(entities)
        stats.relation_instances += len(relations)
        stats.dependency_links += sum(relation.get("type") == "DEPENDS_ON" for relation in relations)
        stats.multiple_task_messages += len(tasks) > 1
        stats.entity_labels.update(str(entity.get("type")) for entity in entities)
        stats.relation_labels.update(str(relation.get("type")) for relation in relations)
        for task in tasks:
            attributes = task.get("task_attributes") or {}
            stats.task_operations[str(attributes.get("operation"))] += 1
            stats.task_statuses[str(attributes.get("status"))] += 1
    return stats


def _human_verified(record: Mapping[str, Any]) -> bool:
    review = record.get("human_review") or (record.get("annotation_provenance") or {}).get("human_review") or {}
    reviewer = review.get("reviewer") or {}
    return (
        review.get("review_status") == "COMPLETED"
        and review.get("quality_tier") in {"GOLD", "SILVER"}
        and isinstance(reviewer.get("reviewer_id"), str)
        and bool(reviewer.get("completed_at"))
    )


def _gold_verified(record: Mapping[str, Any]) -> bool:
    review = record.get("human_review") or {}
    return _human_verified(record) and review.get("quality_tier") == "GOLD"


def _annotation_source_records(paths: Sequence[Path | str]) -> list[tuple[Path, dict[str, Any]]]:
    values = []
    for path_value in paths:
        path = Path(path_value)
        values.extend((path, record) for record in read_jsonl(path))
    return values


def _validate_annotation_candidate(
    record: Mapping[str, Any],
    cleaned: Mapping[str, Any],
    expected_source_split: str,
) -> list[str]:
    errors = []
    if record.get("id") != cleaned.get("id"):
        errors.append("record_id_mismatch")
    if record.get("source_split") != expected_source_split or cleaned.get("source_split") != expected_source_split:
        errors.append("source_split_mismatch")
    if record.get("thread_id") != cleaned.get("thread_id"):
        errors.append("thread_id_mismatch")
    if record.get("text") != cleaned.get("text"):
        errors.append("cleaned_text_mismatch")
    if "full_data" in str(record.get("source_split", "")).casefold() or "full_data" in str(record.get("source_filename", "")).casefold():
        errors.append("full_data_source_forbidden")
    candidate = copy.deepcopy(cleaned)
    candidate["text2task_annotations"] = copy.deepcopy(record.get("text2task_annotations"))
    issues = validate_record(candidate, require_annotations=True)
    errors.extend(f"{issue.code}:{issue.path}" for issue in issues)
    return errors


def _final_record(
    cleaned: Mapping[str, Any],
    annotated: Mapping[str, Any],
    tier: str,
    annotation_path: Path,
) -> dict[str, Any]:
    output = copy.deepcopy(cleaned)
    output["text2task_annotations"] = copy.deepcopy(annotated.get("text2task_annotations"))
    output["annotation_provenance"] = {
        "quality_tier": tier,
        "annotation_source_file": str(annotation_path),
        "human_review": copy.deepcopy(annotated.get("human_review")),
        "llm_annotation_metadata": copy.deepcopy(
            annotated.get("llm_annotation_metadata") or annotated.get("llm_prediction_metadata")
        ),
    }
    # Keep MailEx labels and source history distinct from Text2Task labels.
    output["source_provenance"] = {
        "source": cleaned.get("source"),
        "source_split": cleaned.get("source_split"),
        "source_filename": cleaned.get("source_filename"),
        "thread_id": cleaned.get("thread_id"),
        "turn_index": cleaned.get("turn_index"),
        "original_events_preserved": "original_events" in cleaned,
        "cleaning": copy.deepcopy(cleaned.get("cleaning")),
    }
    return output


@dataclass
class FinalizerConfig:
    cleaned_dir: Path
    gold_dir: Path
    silver_paths: list[Path]
    rejected_dir: Path
    output_dir: Path
    report_path: Path
    integrity_path: Path
    small_test_threshold: int = 5
    allow_silver_evaluation: bool = False


def assemble_dataset(config: FinalizerConfig) -> dict[str, Any]:
    cleaned_by_split: dict[str, dict[str, dict[str, Any]]] = {}
    cleaned_records_by_split: dict[str, list[dict[str, Any]]] = {}
    source_thread_splits: dict[str, set[str]] = defaultdict(set)
    source_id_splits: dict[str, set[str]] = defaultdict(set)
    for source_split in SOURCE_TO_FINAL:
        path = config.cleaned_dir / f"{source_split}.jsonl"
        records = read_jsonl(path)
        cleaned_records_by_split[source_split] = records
        mapping: dict[str, dict[str, Any]] = {}
        for record in records:
            record_id = record.get("id")
            if not isinstance(record_id, str):
                raise ValueError(f"Cleaned record missing id: {path}")
            if record_id in mapping:
                raise ValueError(f"Duplicate cleaned ID within {source_split}: {record_id}")
            mapping[record_id] = record
            source_thread_splits[str(record.get("thread_id"))].add(source_split)
            source_id_splits[record_id].add(source_split)
        cleaned_by_split[source_split] = mapping

    cross_split_threads = {thread: sorted(splits) for thread, splits in source_thread_splits.items() if len(splits) > 1}
    cross_split_ids = {record_id: sorted(splits) for record_id, splits in source_id_splits.items() if len(splits) > 1}
    source_duplicates = duplicate_audit(cleaned_records_by_split)

    rejected_ids = {
        str(record.get("id"))
        for split in SOURCE_TO_FINAL
        for record in read_jsonl(config.rejected_dir / f"{split}.jsonl")
    }
    quarantined: list[dict[str, Any]] = []
    selected: dict[str, dict[str, Any]] = {}
    selected_priority: dict[str, int] = {}

    # Gold has precedence over reviewed silver and raw LLM silver.
    sources: list[tuple[str, int, Path, dict[str, Any]]] = []
    for split in SOURCE_TO_FINAL:
        gold_path = config.gold_dir / f"{split}.jsonl"
        sources.extend(("GOLD", 3, gold_path, record) for record in read_jsonl(gold_path))
    for silver_path in config.silver_paths:
        sources.extend(("SILVER", 2 if _human_verified(record) else 1, silver_path, record) for record in read_jsonl(silver_path))

    for tier, priority, path, annotated in sources:
        record_id = annotated.get("id")
        source_split = annotated.get("source_split")
        if not isinstance(record_id, str) or source_split not in SOURCE_TO_FINAL:
            quarantined.append({"record_id": record_id, "source_file": str(path), "reasons": ["invalid_id_or_source_split"]})
            continue
        if record_id in rejected_ids:
            quarantined.append({"record_id": record_id, "source_file": str(path), "reasons": ["explicitly_rejected"]})
            continue
        cleaned = cleaned_by_split[source_split].get(record_id)
        if cleaned is None:
            quarantined.append({"record_id": record_id, "source_file": str(path), "reasons": ["missing_cleaned_source"]})
            continue
        final_split = SOURCE_TO_FINAL[source_split]
        if tier == "GOLD" and not _gold_verified(annotated):
            quarantined.append({"record_id": record_id, "source_file": str(path), "reasons": ["gold_not_human_verified"]})
            continue
        if final_split in {"validation", "test"} and not _gold_verified(annotated) and not config.allow_silver_evaluation:
            quarantined.append({"record_id": record_id, "source_file": str(path), "reasons": ["evaluation_requires_human_verified_gold"]})
            continue
        errors = _validate_annotation_candidate(annotated, cleaned, source_split)
        if errors:
            quarantined.append({"record_id": record_id, "source_file": str(path), "reasons": errors})
            continue
        if priority <= selected_priority.get(record_id, -1):
            continue
        selected[record_id] = _final_record(cleaned, annotated, tier, path)
        selected_priority[record_id] = priority

    outputs: dict[str, list[dict[str, Any]]] = {split: [] for split in FINAL_TO_SOURCE}
    for record in selected.values():
        outputs[SOURCE_TO_FINAL[str(record.get("source_split"))]].append(record)
    for records in outputs.values():
        records.sort(key=lambda item: (str(item.get("thread_id", "")), int(item.get("turn_index", 0)), str(item.get("id", ""))))

    # Quarantine lower-priority whole threads if eligible output still contains
    # a cross-split exact or near duplicate.
    final_duplicate_audit = duplicate_audit(outputs)
    duplicate_pairs: list[tuple[str, str]] = []
    for group in final_duplicate_audit["exact_cross_split_groups"]:
        ids = group["record_ids"]
        duplicate_pairs.extend((ids[left], ids[right]) for left in range(len(ids)) for right in range(left + 1, len(ids)))
    duplicate_pairs.extend((pair["left_id"], pair["right_id"]) for pair in final_duplicate_audit["near_cross_split_pairs"])
    record_lookup = {str(record.get("id")): (split, record) for split, records in outputs.items() for record in records}
    threads_to_remove: set[tuple[str, str]] = set()
    for left_id, right_id in duplicate_pairs:
        if left_id not in record_lookup or right_id not in record_lookup:
            continue
        left_split, left = record_lookup[left_id]
        right_split, right = record_lookup[right_id]
        remove_split, remove_record = (left_split, left) if SPLIT_PRIORITY[left_split] < SPLIT_PRIORITY[right_split] else (right_split, right)
        threads_to_remove.add((remove_split, str(remove_record.get("thread_id"))))
    if threads_to_remove:
        for split, thread_id in sorted(threads_to_remove):
            retained = []
            for record in outputs[split]:
                if str(record.get("thread_id")) == thread_id:
                    quarantined.append({"record_id": record.get("id"), "source_file": "assembled_output", "reasons": ["cross_split_near_or_exact_duplicate_thread"]})
                else:
                    retained.append(record)
            outputs[split] = retained
        final_duplicate_audit = duplicate_audit(outputs)

    final_ids = [str(record.get("id")) for records in outputs.values() for record in records]
    full_data_count = sum(
        "full_data" in str(record.get("source_split", "")).casefold()
        or "full_data" in str(record.get("source_filename", "")).casefold()
        for records in outputs.values()
        for record in records
    )
    stats = {split: summarize_split(records) for split, records in outputs.items()}
    human_eval_counts = {
        split: sum(_human_verified(record) for record in outputs[split])
        for split in ("validation", "test")
    }

    blocking_issues = []
    if cross_split_threads:
        blocking_issues.append("source_thread_ids_cross_original_splits")
    if cross_split_ids:
        blocking_issues.append("source_record_ids_cross_original_splits")
    if len(final_ids) != len(set(final_ids)):
        blocking_issues.append("duplicate_final_record_ids")
    if full_data_count:
        blocking_issues.append("full_data_records_present")
    if final_duplicate_audit["exact_cross_split_groups"] or final_duplicate_audit["near_cross_split_pairs"]:
        blocking_issues.append("cross_split_message_duplicates_remain")
    if stats["validation"].emails == 0:
        blocking_issues.append("validation_split_is_empty")
    if stats["test"].emails == 0:
        blocking_issues.append("test_split_is_empty")
    if human_eval_counts["validation"] == 0 and not config.allow_silver_evaluation:
        blocking_issues.append("validation_has_no_human_verified_examples")
    if human_eval_counts["test"] == 0 and not config.allow_silver_evaluation:
        blocking_issues.append("test_has_no_human_verified_examples")
    if stats["train"].emails == 0:
        blocking_issues.append("training_split_is_empty")

    small_test_classes = []
    for label in EXPECTED_ENTITY_LABELS:
        count = stats["test"].entity_labels.get(label, 0)
        if count < config.small_test_threshold:
            small_test_classes.append({"class_family": "entity", "label": label, "count": count, "threshold": config.small_test_threshold})
    for label in EXPECTED_RELATION_LABELS:
        count = stats["test"].relation_labels.get(label, 0)
        if count < config.small_test_threshold:
            small_test_classes.append({"class_family": "relation", "label": label, "count": count, "threshold": config.small_test_threshold})

    for split, records in outputs.items():
        atomic_jsonl(config.output_dir / f"{split}.jsonl", records)

    status = "NOT_READY" if blocking_issues else ("READY_SILVER_ONLY" if config.allow_silver_evaluation else "READY")
    integrity = {
        "report_version": "1.0.0",
        "generated_at": utc_now(),
        "ready_for_ml": not blocking_issues,
        "status": status,
        "blocking_issues": blocking_issues,
        "silver_evaluation_override": config.allow_silver_evaluation,
        "quality_warnings": ([
            "Validation and test annotations are AI-generated SILVER, not human-verified GOLD; reported metrics measure agreement with silver labels only."
        ] if config.allow_silver_evaluation else []),
        "split_policy": {
            "train": "human GOLD and valid silver from original MailEx train only",
            "validation": ("valid AI SILVER from original MailEx dev (explicit user override)" if config.allow_silver_evaluation else "human-verified GOLD from original MailEx dev only"),
            "test": ("valid AI SILVER from original MailEx test (explicit user override)" if config.allow_silver_evaluation else "human-verified GOLD from original MailEx test only"),
            "test_feedback_policy": "test labels and outcomes must not tune prompts, models, or training configurations",
        },
        "source_cleaned_counts": {split: len(records) for split, records in cleaned_records_by_split.items()},
        "source_thread_split_conflicts": cross_split_threads,
        "source_id_split_conflicts": cross_split_ids,
        "source_duplicate_audit": source_duplicates,
        "final_duplicate_audit": final_duplicate_audit,
        "full_data_records_in_final": full_data_count,
        "rejected_ids_count": len(rejected_ids),
        "quarantined_annotations": quarantined,
        "human_verified_evaluation_counts": human_eval_counts,
        "split_statistics": {split: value.to_dict() for split, value in stats.items()},
        "small_test_classes": small_test_classes,
    }
    atomic_json(config.integrity_path, integrity)
    write_statistics_report(config.report_path, integrity)
    return integrity


def write_statistics_report(path: Path, integrity: Mapping[str, Any]) -> None:
    stats = integrity["split_statistics"]
    lines = [
        "# Text2Task final dataset statistics",
        "",
        f"Generated: {integrity['generated_at']}",
        "",
        f"**Dataset status: {integrity['status']}**",
        "",
    ]
    if integrity["blocking_issues"]:
        lines.extend(["## Blocking issues", ""])
        lines.extend(f"- `{issue}`" for issue in integrity["blocking_issues"])
        lines.extend([
            "",
            "The files were generated as an honest snapshot, but the dataset must not be treated as complete or used for model selection. No examples were fabricated or promoted automatically.",
            "",
        ])
    if integrity.get("quality_warnings"):
        lines.extend(["## Quality warning", ""])
        lines.extend(f"- {warning}" for warning in integrity["quality_warnings"])
        lines.append("")
    lines.extend(["## Final split totals", ""])
    for split in ("train", "validation", "test"):
        value = stats[split]
        lines.extend([
            f"### {split}",
            "",
            f"- Threads: {value['threads']}",
            f"- Emails: {value['emails']}",
            f"- Tasks: {value['tasks']}",
            f"- Entity spans: {value['entity_spans']}",
            f"- Relation instances: {value['relation_instances']}",
            f"- Dependency links: {value['dependency_links']}",
            f"- Messages with multiple tasks: {value['multiple_task_messages']}",
            f"- GOLD records: {value['gold_records']}",
            f"- SILVER records: {value['silver_records']}",
            "",
            f"Entity labels: `{json.dumps(value['entity_labels'], sort_keys=True)}`",
            "",
            f"Relation labels: `{json.dumps(value['relation_labels'], sort_keys=True)}`",
            "",
            f"Task operations: `{json.dumps(value['task_operations'], sort_keys=True)}`",
            "",
            f"Task statuses: `{json.dumps(value['task_statuses'], sort_keys=True)}`",
            "",
        ])
    lines.extend([
        "## Split integrity",
        "",
        f"- Full-data records included: {integrity['full_data_records_in_final']}",
        f"- Cross-split source thread conflicts: {len(integrity['source_thread_split_conflicts'])}",
        f"- Cleaned-source exact cross-split duplicate groups: {len(integrity['source_duplicate_audit']['exact_cross_split_groups'])}",
        f"- Cleaned-source high-confidence near-duplicate pairs: {len(integrity['source_duplicate_audit']['near_cross_split_pairs'])}",
        f"- Final exact cross-split duplicate groups: {len(integrity['final_duplicate_audit']['exact_cross_split_groups'])}",
        f"- Final near-duplicate cross-split pairs: {len(integrity['final_duplicate_audit']['near_cross_split_pairs'])}",
        f"- Human-verified validation examples: {integrity['human_verified_evaluation_counts']['validation']}",
        f"- Human-verified test examples: {integrity['human_verified_evaluation_counts']['test']}",
        f"- Quarantined annotations: {len(integrity['quarantined_annotations'])}",
        "",
        "## Test classes too small for meaningful evaluation",
        "",
    ])
    for item in integrity["small_test_classes"]:
        lines.append(f"- {item['class_family']} `{item['label']}`: {item['count']} instance(s); minimum reporting threshold is {item['threshold']}")
    if not integrity["small_test_classes"]:
        lines.append("None at the configured threshold.")
    lines.extend([
        "",
        "## Provenance policy",
        "",
        "Each final record keeps `original_events` from MailEx, `source_provenance` for cleaned-source history, `text2task_annotations` for experiment labels, and `annotation_provenance` identifying GOLD versus SILVER. Test outcomes are isolated from prompt and training-configuration decisions.",
        "",
        "Complete duplicate findings, quarantines, validation state, and machine-readable counts are in `data/reports/split_integrity.json`.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)


def format_summary(integrity: Mapping[str, Any]) -> str:
    lines = [f"Text2Task final dataset status: {integrity['status']}"]
    for split in ("train", "validation", "test"):
        stats = integrity["split_statistics"][split]
        lines.append(
            f"  {split}: threads={stats['threads']} emails={stats['emails']} tasks={stats['tasks']} "
            f"entities={stats['entity_spans']} relations={stats['relation_instances']} dependencies={stats['dependency_links']}"
        )
    if integrity["blocking_issues"]:
        lines.append("  Blocking issues: " + ", ".join(integrity["blocking_issues"]))
    return "\n".join(lines)
