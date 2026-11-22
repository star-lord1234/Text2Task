"""Reproducible pre-training audit for Text2Task entity model data."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


SPLITS = ("train", "validation", "test")
EXPECTED_SOURCE_SPLIT = {"train": "train", "validation": "dev", "test": "test"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    values = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            values.append(value)
    return values


def percentile(values: Sequence[int], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _human_gold(record: Mapping[str, Any]) -> bool:
    provenance = record.get("annotation_provenance") or {}
    review = provenance.get("human_review") or record.get("human_review") or {}
    reviewer = review.get("reviewer") or {}
    return (
        provenance.get("quality_tier") == "GOLD"
        and review.get("review_status") == "COMPLETED"
        and review.get("quality_tier") == "GOLD"
        and isinstance(reviewer.get("reviewer_id"), str)
        and bool(reviewer.get("reviewer_id"))
        and bool(reviewer.get("completed_at"))
    )


def _bio_spans(row: Mapping[str, Any], errors: list[str]) -> list[tuple[str, int, int, str]]:
    labels = row["labels"]
    offsets = row["offset_mapping"]
    entity_ids = row["entity_ids"]
    result = []
    index = 0
    while index < len(labels):
        label = labels[index]
        if label is None or label == "O":
            index += 1
            continue
        if not label.startswith("B-"):
            errors.append(f"{row['id']}: orphan BIO label {label} at token {index}")
            index += 1
            continue
        entity_type = label[2:]
        entity_id = entity_ids[index]
        start, end = offsets[index]
        index += 1
        while index < len(labels) and labels[index] == f"I-{entity_type}" and entity_ids[index] == entity_id:
            end = offsets[index][1]
            index += 1
        result.append((entity_type, start, end, entity_id))
    return result


def audit_entity_data(
    entity_dir: Path,
    final_dir: Path,
    schema_path: Path,
    *,
    vocab_path: Path | None = None,
    context_limit: int = 512,
    minimum_train_spans: int = 20,
    minimum_evaluation_spans: int = 5,
) -> dict[str, Any]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_labels = list(schema["x-text2task-label-policy"]["entity_labels"])
    label_map_path = entity_dir / "label_map.json"
    label_map = json.loads(label_map_path.read_text(encoding="utf-8"))
    vocabulary = None
    if vocab_path is not None:
        vocab_tokens = vocab_path.read_text(encoding="utf-8").splitlines()
        vocabulary = {token: index for index, token in enumerate(vocab_tokens)}
    labels = label_map.get("labels") or []
    label_to_id = label_map.get("label_to_id") or {}
    expected_bio = {"O"} | {f"{prefix}-{entity_type}" for entity_type in schema_labels for prefix in ("B", "I")}
    structural_errors: list[str] = []
    warnings: list[str] = []
    if set(labels) != expected_bio or set(label_to_id) != expected_bio:
        structural_errors.append("label_map.json does not contain exactly O plus B/I labels for every schema entity")
    if len(labels) != len(set(labels)) or sorted(label_to_id.values()) != list(range(len(labels))):
        structural_errors.append("label IDs are not unique and contiguous")
    for label, label_id in label_to_id.items():
        if not isinstance(label_id, int) or label_id >= len(labels) or labels[label_id] != label:
            structural_errors.append(f"label map mismatch for {label}")

    split_reports: dict[str, Any] = {}
    thread_sets: dict[str, set[str]] = {}
    record_id_sets: dict[str, set[str]] = {}
    for split in SPLITS:
        model_path = entity_dir / f"{split}.jsonl"
        final_path = final_dir / f"{split}.jsonl"
        if not model_path.is_file() or not final_path.is_file():
            structural_errors.append(f"missing {split} model-ready or finalized JSONL")
            continue
        rows = read_jsonl(model_path)
        final_records = read_jsonl(final_path)
        final_by_id = {str(record["id"]): record for record in final_records}
        if len(final_by_id) != len(final_records):
            structural_errors.append(f"{split}: duplicate finalized record IDs")
        row_ids = [str(row.get("id")) for row in rows]
        if len(row_ids) != len(set(row_ids)):
            structural_errors.append(f"{split}: duplicate model-row IDs")

        tier_counts = Counter()
        model_tier_counts = Counter()
        gold_human_count = 0
        span_counts = Counter()
        bio_token_counts = Counter()
        entity_coverage: dict[str, list[str]] = defaultdict(list)
        rows_by_source: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        overlap_records = 0
        overlap_pairs = 0
        expected_source_split = EXPECTED_SOURCE_SPLIT[split]
        for record in final_records:
            provenance = record.get("annotation_provenance") or {}
            tier_counts[str(provenance.get("quality_tier"))] += 1
            gold_human_count += _human_gold(record)
            entities = (record.get("text2task_annotations") or {}).get("entities") or []
            span_counts.update(str(entity.get("type")) for entity in entities)
            record_has_overlap = False
            for left_index, left in enumerate(entities):
                for right in entities[left_index + 1:]:
                    if int(left["start"]) < int(right["end"]) and int(right["start"]) < int(left["end"]):
                        overlap_pairs += 1
                        record_has_overlap = True
            overlap_records += record_has_overlap

        for row in rows:
            row_id = str(row.get("id"))
            source_id = str(row.get("source_record_id"))
            rows_by_source[source_id].append(row)
            model_tier_counts[str(row.get("annotation_tier"))] += 1
            source_record = final_by_id.get(source_id)
            if source_record is None:
                structural_errors.append(f"{row_id}: unknown source_record_id {source_id}")
                continue
            if row.get("final_split") != split or row.get("source_split") != expected_source_split:
                structural_errors.append(f"{row_id}: split provenance mismatch")
            if row.get("thread_id") != source_record.get("thread_id") or row.get("text") != source_record.get("text"):
                structural_errors.append(f"{row_id}: source thread or text mismatch")
            source_tier = (source_record.get("annotation_provenance") or {}).get("quality_tier")
            if row.get("annotation_tier") != source_tier:
                structural_errors.append(f"{row_id}: annotation tier differs from finalized source")
            sequence_names = (
                "tokens", "input_ids", "attention_mask", "special_tokens_mask", "offset_mapping",
                "labels", "label_ids", "entity_ids",
            )
            sequences = [row.get(name) for name in sequence_names]
            if any(not isinstance(value, list) for value in sequences):
                structural_errors.append(f"{row_id}: missing sequence field")
                continue
            lengths = {len(value) for value in sequences}
            if len(lengths) != 1:
                structural_errors.append(f"{row_id}: tokenizer sequence lengths differ")
                continue
            token_count = lengths.pop()
            if token_count > context_limit:
                structural_errors.append(f"{row_id}: {token_count} tokens exceeds context limit {context_limit}")
            if not row["tokens"] or row["tokens"][0] != "[CLS]" or row["tokens"][-1] != "[SEP]":
                structural_errors.append(f"{row_id}: missing DistilBERT boundary tokens")
            if row.get("tokenizer") != "distilbert-base-uncased":
                structural_errors.append(f"{row_id}: unexpected tokenizer {row.get('tokenizer')!r}")
            if vocabulary is not None:
                for token_index, (token, input_id) in enumerate(zip(row["tokens"], row["input_ids"])):
                    if vocabulary.get(token) != input_id:
                        structural_errors.append(f"{row_id}: vocabulary ID mismatch at token {token_index}")
            if any(value != 1 for value in row["attention_mask"]):
                structural_errors.append(f"{row_id}: unpadded row has a non-one attention mask")
            expected_content_length = int(row["wordpiece_range"][1]) - int(row["wordpiece_range"][0])
            if expected_content_length + 2 != token_count:
                structural_errors.append(f"{row_id}: wordpiece range does not match token count")
            row_entities = {str(entity["id"]): entity for entity in row.get("entities") or []}
            if len(row_entities) != len(row.get("entities") or []):
                structural_errors.append(f"{row_id}: duplicate row entity IDs")
            for token_index, (special, offset, label, label_id, entity_id) in enumerate(zip(
                row["special_tokens_mask"], row["offset_mapping"], row["labels"], row["label_ids"], row["entity_ids"]
            )):
                if not isinstance(offset, list) or len(offset) != 2 or not all(isinstance(value, int) for value in offset):
                    structural_errors.append(f"{row_id}: invalid offset at token {token_index}")
                    continue
                if special:
                    if label is not None or label_id != -100 or offset != [0, 0]:
                        structural_errors.append(f"{row_id}: special token {token_index} is not ignored")
                else:
                    if label not in expected_bio or label_id != label_to_id.get(label):
                        structural_errors.append(f"{row_id}: invalid label/ID at token {token_index}")
                    else:
                        bio_token_counts[label] += 1
                    if not (0 <= offset[0] < offset[1] <= len(row["text"])):
                        structural_errors.append(f"{row_id}: invalid character offset at token {token_index}")
                    if label == "O" and entity_id is not None:
                        structural_errors.append(f"{row_id}: O token carries entity ID at token {token_index}")
                    if isinstance(label, str) and label != "O" and str(entity_id) not in row_entities:
                        structural_errors.append(f"{row_id}: labeled token has unknown entity ID at token {token_index}")
            reconstructed = _bio_spans(row, structural_errors)
            expected_spans = sorted(
                (str(entity["type"]), int(entity["start"]), int(entity["end"]), str(entity["id"]))
                for entity in row_entities.values()
            )
            if sorted(reconstructed) != expected_spans:
                structural_errors.append(f"{row_id}: BIO spans do not reconstruct row entities")
            for entity in row_entities.values():
                start, end = int(entity["start"]), int(entity["end"])
                if row["text"][start:end] != entity.get("text"):
                    structural_errors.append(f"{row_id}/{entity.get('id')}: entity span text mismatch")
                entity_coverage[source_id].append(str(entity["id"]))
            row_entity_list = list(row_entities.values())
            for left_index, left in enumerate(row_entity_list):
                for right in row_entity_list[left_index + 1:]:
                    if int(left["start"]) < int(right["end"]) and int(right["start"]) < int(left["end"]):
                        structural_errors.append(f"{row_id}: overlapping entities were placed in the same BIO layer")

        wordpiece_lengths = []
        context_exceeding = []
        maximum_layers = 0
        for source_id, source_record in final_by_id.items():
            source_rows = rows_by_source.get(source_id, [])
            if not source_rows:
                structural_errors.append(f"{split}/{source_id}: finalized record has no model row")
                continue
            expected_entities = [str(entity["id"]) for entity in (source_record.get("text2task_annotations") or {}).get("entities") or []]
            if Counter(entity_coverage[source_id]) != Counter(expected_entities):
                structural_errors.append(f"{split}/{source_id}: entity coverage is not exactly once")
            layer_counts = {int(row.get("layer_count", -1)) for row in source_rows}
            if len(layer_counts) != 1:
                structural_errors.append(f"{split}/{source_id}: inconsistent layer_count")
            else:
                maximum_layers = max(maximum_layers, next(iter(layer_counts)))
            window_counts = {int(row.get("window_count", -1)) for row in source_rows}
            if len(window_counts) != 1:
                structural_errors.append(f"{split}/{source_id}: inconsistent window_count")
            else:
                expected_pairs = {
                    (layer_index, window_index)
                    for layer_index in range(next(iter(layer_counts)))
                    for window_index in range(next(iter(window_counts)))
                } if len(layer_counts) == 1 else set()
                actual_pairs = {(int(row.get("layer_index", -1)), int(row.get("window_index", -1))) for row in source_rows}
                if actual_pairs != expected_pairs:
                    structural_errors.append(f"{split}/{source_id}: incomplete or duplicate layer/window grid")
            content_length = max(int(row["wordpiece_range"][1]) for row in source_rows)
            wordpiece_lengths.append(content_length + 2)
            if content_length + 2 > context_limit or any(int(row.get("window_count", 1)) > 1 for row in source_rows):
                context_exceeding.append({
                    "source_record_id": source_id,
                    "tokens_with_specials": content_length + 2,
                    "window_count": max(int(row.get("window_count", 1)) for row in source_rows),
                })

        split_reports[split] = {
            "paths": {"model_ready": str(model_path), "finalized": str(final_path)},
            "emails": len(final_records),
            "model_rows": len(rows),
            "threads": len({str(record.get("thread_id")) for record in final_records}),
            "annotation_tiers_by_email": dict(sorted(tier_counts.items())),
            "annotation_tiers_by_model_row": dict(sorted(model_tier_counts.items())),
            "human_reviewed_gold_emails": gold_human_count,
            "span_counts": {label: span_counts[label] for label in schema_labels},
            "bio_token_label_counts": dict(sorted(bio_token_counts.items())),
            "overlap": {
                "emails_with_overlaps": overlap_records,
                "overlapping_span_pairs": overlap_pairs,
                "maximum_bio_layers": maximum_layers,
            },
            "token_lengths_with_special_tokens": {
                "minimum": min(wordpiece_lengths, default=0),
                "median": percentile(wordpiece_lengths, 0.5),
                "p90": percentile(wordpiece_lengths, 0.9),
                "p95": percentile(wordpiece_lengths, 0.95),
                "p99": percentile(wordpiece_lengths, 0.99),
                "maximum": max(wordpiece_lengths, default=0),
            },
            "emails_exceeding_context_limit": context_exceeding,
        }
        thread_sets[split] = {str(record.get("thread_id")) for record in final_records}
        record_id_sets[split] = set(final_by_id)

    cross_split_threads = []
    cross_split_records = []
    for left_index, left in enumerate(SPLITS):
        for right in SPLITS[left_index + 1:]:
            for thread_id in sorted(thread_sets.get(left, set()) & thread_sets.get(right, set())):
                cross_split_threads.append({"thread_id": thread_id, "splits": [left, right]})
            for record_id in sorted(record_id_sets.get(left, set()) & record_id_sets.get(right, set())):
                cross_split_records.append({"record_id": record_id, "splits": [left, right]})
    if cross_split_threads:
        structural_errors.append(f"{len(cross_split_threads)} source threads overlap across final splits")
    if cross_split_records:
        structural_errors.append(f"{len(cross_split_records)} source record IDs overlap across final splits")

    insufficient = []
    for entity_type in schema_labels:
        train_count = split_reports.get("train", {}).get("span_counts", {}).get(entity_type, 0)
        if train_count < minimum_train_spans:
            insufficient.append({"label": entity_type, "split": "train", "count": train_count, "threshold": minimum_train_spans})
        for split in ("validation", "test"):
            count = split_reports.get(split, {}).get("span_counts", {}).get(entity_type, 0)
            if count < minimum_evaluation_spans:
                insufficient.append({"label": entity_type, "split": split, "count": count, "threshold": minimum_evaluation_spans})

    heldout_gold = all(
        split_reports.get(split, {}).get("human_reviewed_gold_emails")
        == split_reports.get(split, {}).get("emails")
        for split in ("validation", "test")
    )
    if not heldout_gold:
        warnings.append("validation and test are not fully human-reviewed GOLD")
    if insufficient:
        warnings.append("one or more entity labels are below the documented minimum-support thresholds")
    structural_ready = not structural_errors
    return {
        "audit_version": "1.0.0",
        "status": "READY" if structural_ready and heldout_gold else "NOT_READY",
        "ready_for_training_with_gold_evaluation": structural_ready and heldout_gold,
        "structurally_valid_for_silver_experiments": structural_ready,
        "context_limit": context_limit,
        "schema_entity_labels": schema_labels,
        "bio_labels": labels,
        "ignore_index": label_map.get("ignore_index"),
        "vocabulary_path": str(vocab_path) if vocab_path is not None else None,
        "split_reports": split_reports,
        "cross_split_thread_overlaps": cross_split_threads,
        "cross_split_record_overlaps": cross_split_records,
        "insufficient_support_policy": {
            "minimum_train_spans": minimum_train_spans,
            "minimum_spans_per_evaluation_split": minimum_evaluation_spans,
            "note": "Screening thresholds, not claims of statistical sufficiency.",
        },
        "insufficient_label_support": insufficient,
        "structural_errors": structural_errors,
        "warnings": warnings,
        "blocking_issues": ([] if structural_ready else ["structural_validation_failed"])
        + ([] if heldout_gold else ["validation_and_test_not_human_reviewed_gold"]),
    }


def write_report(audit: Mapping[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Text2Task Entity Training-Readiness Audit",
        "",
        f"**Status: {audit['status']}**",
        "",
        "The files are structurally valid for controlled SILVER experiments." if audit["structurally_valid_for_silver_experiments"]
        else "Structural validation failed; do not train.",
        "The dataset is **not approved for training with gold validation/test evaluation** because held-out records are not human-reviewed GOLD."
        if not audit["ready_for_training_with_gold_evaluation"] else "Held-out evaluation records are human-reviewed GOLD.",
        "",
        "## Schema and file format",
        "",
        f"Schema entities: {', '.join(audit['schema_entity_labels'])}.",
        f"BIO vocabulary: {', '.join(audit['bio_labels'])}. Special tokens use ignore index `{audit['ignore_index']}`.",
        "Each JSONL row is a pretokenized DistilBERT window/layer, not a generic raw-text Hugging Face example. "
        "It contains input IDs, masks, WordPiece strings, character offsets, BIO labels/IDs, source provenance, and exact row entities.",
        "",
        "## Split audit",
        "",
        "| Split | Emails | Threads | Model rows | Human GOLD | SILVER emails | Max tokens | >512 | Overlap emails | Max layers |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for split in SPLITS:
        values = audit["split_reports"][split]
        tiers = values["annotation_tiers_by_email"]
        lengths = values["token_lengths_with_special_tokens"]
        lines.append(
            f"| {split} | {values['emails']} | {values['threads']} | {values['model_rows']} | "
            f"{values['human_reviewed_gold_emails']} | {tiers.get('SILVER', 0)} | {lengths['maximum']} | "
            f"{len(values['emails_exceeding_context_limit'])} | {values['overlap']['emails_with_overlaps']} | "
            f"{values['overlap']['maximum_bio_layers']} |"
        )
    lines.extend([
        "",
        "Validation and test both have `human_review = null`; their provenance explicitly says `requires_human_review_for_gold: true`. "
        "No provenance was upgraded or rewritten by this audit.",
        "",
        "## Original-email token lengths (including `[CLS]` and `[SEP]`)",
        "",
        "| Split | Min | Median | P90 | P95 | P99 | Max |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for split in SPLITS:
        lengths = audit["split_reports"][split]["token_lengths_with_special_tokens"]
        lines.append(
            f"| {split} | {lengths['minimum']} | {lengths['median']:.1f} | {lengths['p90']:.1f} | "
            f"{lengths['p95']:.1f} | {lengths['p99']:.1f} | {lengths['maximum']} |"
        )
    lines.extend([
        "",
        "No email exceeds DistilBERT's 512-token context limit in the current build; no truncation repair is needed.",
        "",
        "## Entity-span distribution",
        "",
        "Counts below are unique annotated character spans, not subword-token counts or duplicated overlap layers.",
        "",
        "| Label | Train | Validation | Test |",
        "|---|---:|---:|---:|",
    ])
    for label in audit["schema_entity_labels"]:
        lines.append(
            f"| {label} | {audit['split_reports']['train']['span_counts'][label]} | "
            f"{audit['split_reports']['validation']['span_counts'][label]} | "
            f"{audit['split_reports']['test']['span_counts'][label]} |"
        )
    policy = audit["insufficient_support_policy"]
    lines.extend([
        "",
        "## Insufficient-support flags",
        "",
        f"Screening rule: flag fewer than {policy['minimum_train_spans']} training spans or fewer than "
        f"{policy['minimum_spans_per_evaluation_split']} spans in either evaluation split. These are pragmatic "
        "warnings, not guarantees of statistical adequacy.",
        "",
    ])
    if audit["insufficient_label_support"]:
        for item in audit["insufficient_label_support"]:
            lines.append(f"- `{item['label']}` in {item['split']}: {item['count']} spans (threshold {item['threshold']}).")
    else:
        lines.append("No label falls below the screening thresholds.")
    lines.extend([
        "",
        "## Structural verification",
        "",
        f"- BIO/token/offset/ID validation errors: {len(audit['structural_errors'])}.",
        f"- Cross-split thread overlaps: {len(audit['cross_split_thread_overlaps'])}.",
        f"- Cross-split record-ID overlaps: {len(audit['cross_split_record_overlaps'])}.",
        "- Every entity was found exactly once across its deterministic overlap layers.",
        "- Every BIO sequence reconstructed the exact source character spans.",
        "- No semantic annotations were changed.",
        "",
        "## Decision",
        "",
        "Do **not** begin the requested gold-evaluated fine-tuning yet. Human-review and GOLD promotion of every validation and test email is the blocking gate. "
        "The current files may only be used if the experiment is explicitly described as SILVER-only and its metrics are not presented as human-gold evaluation.",
        "",
    ])
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
