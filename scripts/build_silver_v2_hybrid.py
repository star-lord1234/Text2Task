#!/usr/bin/env python3
"""Build a complete conservative SILVER-v2 corpus from audited, LLM, and filtered v1 spans.

Precedence is deterministic: corrected training audit, validated local-LLM v2,
then a conservative task filter fitted only on the corrected 30-record training
audit. This script never changes source annotations or creates GOLD labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import FeatureUnion, Pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.annotate_entities_v2 import overlap_report, quality_record, read_jsonl, utc_now  # noqa: E402
from scripts.build_entity_dataset_v2 import resolve_single_layer  # noqa: E402
from src.annotation.semantic_quality import semantic_quality  # noqa: E402


THRESHOLD = 0.65
STRONG_ACTION = re.compile(
    r"\b(please|can you|could you|would you|let me know|need(?:s)? to|have to|must|"
    r"should|plan(?:s|ned)? to|going to|i(?:'ll| will)|we(?:'ll| will)|do not|don't|"
    r"send|review|prepare|schedule|submit|provide|update|complete|call|contact|meet|"
    r"attend|reserve|investigate|check|approve|sign|return|forward|notify|map|bounce)\b",
    re.I,
)
TASK_FRAGMENT = re.compile(
    r"^(thanks?|thank you|fyi|being\b|what you think\??$|do for me\??$|have a (?:great|wonderful) day)",
    re.I,
)
FUTURE_STATE = re.compile(r"\bwill\s+(?:remain|be\s+(?:closed|available|located|owned|responsible))\b", re.I)
PERSON_REJECT = re.compile(
    r"^(all|team|socal|cglf|pira|enron|ferc|questar|transwestern|duferco|"
    r"lg\s*&\s*e|ect investments|ena|ecs)$",
    re.I,
)
ORG_HINT = re.compile(r"\b(corp\.?|corporation|company|committee|department|group|team|inc\.?|llc|ltd\.?)\b", re.I)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def task_overlap_fraction(left: dict[str, Any], right: dict[str, Any]) -> float:
    overlap = max(0, min(int(left["end"]), int(right["end"])) - max(int(left["start"]), int(right["start"])))
    denominator = max(1, min(int(left["end"]) - int(left["start"]), int(right["end"]) - int(right["start"])))
    return overlap / denominator


def feature_text(entity: dict[str, Any]) -> str:
    attrs = entity.get("task_attributes") or {}
    return f"{entity.get('text', '')} __OP_{attrs.get('operation')} __ST_{attrs.get('status')}"


def classifier() -> Pipeline:
    return Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
            ("char", TfidfVectorizer(
                analyzer="char_wb", ngram_range=(3, 5), min_df=2,
                sublinear_tf=True, max_features=4000,
            )),
        ])),
        ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000, C=1.0, random_state=20261102)),
    ])


def fit_filter(audit_rows: list[dict[str, Any]]) -> tuple[Pipeline, dict[str, Any]]:
    features: list[str] = []
    labels: list[int] = []
    groups: list[int] = []
    for group, row in enumerate(audit_rows):
        corrected = [entity for entity in row["corrected_silver_v2_diagnostic"]["entities"] if entity["type"] == "TASK"]
        for entity in row["original_silver_annotations"]["entities"]:
            if entity.get("type") != "TASK":
                continue
            score = max((task_overlap_fraction(entity, target) for target in corrected), default=0.0)
            features.append(feature_text(entity))
            labels.append(int(score >= 0.5))
            groups.append(group)
    model = classifier()
    probabilities = cross_val_predict(
        model, features, labels, groups=groups, cv=GroupKFold(5), method="predict_proba",
    )[:, 1]
    predictions = (probabilities >= THRESHOLD).astype(int)
    report = {
        "training_examples": len(labels),
        "keep_examples": sum(labels),
        "reject_examples": len(labels) - sum(labels),
        "threshold": THRESHOLD,
        "grouped_five_fold_confusion_matrix": confusion_matrix(labels, predictions).tolist(),
        "grouped_five_fold_classification_report": classification_report(
            labels, predictions, output_dict=True, zero_division=0,
        ),
        "scope": "diagnostic annotation repair only; not held-out model accuracy",
    }
    model.fit(features, labels)
    return model, report


def exact_three_class_entities(record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept, rejected = [], []
    text = record["text"]
    annotations = record.get("text2task_annotations") or {}
    for entity in annotations.get("entities", []):
        if entity.get("type") not in {"TASK", "PERSON", "TEMPORAL"}:
            continue
        start, end = entity.get("start"), entity.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)):
            rejected.append({"entity": entity, "reason": "invalid_offset"})
            continue
        if text[start:end] != entity.get("text"):
            rejected.append({"entity": entity, "reason": "surface_mismatch"})
            continue
        kept.append(deepcopy(entity))
    return kept, rejected


def hard_task_rejection(entity: dict[str, Any]) -> str | None:
    surface = str(entity.get("text", "")).strip()
    if TASK_FRAGMENT.search(surface):
        return "task_fragment_or_social_phrase"
    if FUTURE_STATE.search(surface):
        return "future_state_not_action"
    return None


def sanitize_non_tasks(entities: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept, rejected = [], []
    for entity in entities:
        if entity.get("type") == "PERSON":
            surface = str(entity.get("text", "")).strip()
            if PERSON_REJECT.fullmatch(surface) or ORG_HINT.search(surface) or "&" in surface:
                rejected.append({"entity": entity, "reason": "person_organization_or_generic_name_gate"})
                continue
        if entity.get("type") == "TEMPORAL":
            surface = str(entity.get("text", "")).strip().lower()
            if surface.startswith("of the ") or surface in {"on", "at", "when"}:
                rejected.append({"entity": entity, "reason": "temporal_fragment_gate"})
                continue
        kept.append(entity)
    return kept, rejected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-v1", type=Path, default=Path("data/final/train.jsonl"))
    parser.add_argument("--audit-v2", type=Path, default=Path("data/diagnostics/entity_pipeline/audit30_corrected_silver_v2.jsonl"))
    parser.add_argument("--llm-v2", type=Path, default=Path("data/annotations/silver_v2_entities_v202/train.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/annotations/silver_v2_hybrid"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train_rows = read_jsonl(args.train_v1)
    audit_rows = read_jsonl(args.audit_v2)
    audit = {row["id"]: row for row in audit_rows}
    llm_rows = read_jsonl(args.llm_v2) if args.llm_v2.is_file() else []
    llm = {row["id"]: row for row in llm_rows if row.get("single_layer_eligible")}
    model, filter_report = fit_filter(audit_rows)
    output, correction_log = [], []
    source_counts: Counter[str] = Counter()
    entity_counts: Counter[str] = Counter()
    rejected_counts: Counter[str] = Counter()

    for record in train_rows:
        record_id = record["id"]
        rejected: list[dict[str, Any]] = []
        if record_id in audit:
            candidates = deepcopy(audit[record_id]["corrected_silver_v2_diagnostic"]["entities"])
            source = "corrected_30_record_diagnostic_audit"
            source_detail = {"audit_severity": audit[record_id]["audit_severity"]}
        elif record_id in llm:
            candidates = deepcopy(llm[record_id]["silver_v2_entities"])
            source = "validated_local_llm_v2"
            source_detail = deepcopy(llm[record_id]["annotation_provenance"])
        else:
            exact, rejected = exact_three_class_entities(record)
            candidates = [entity for entity in exact if entity["type"] != "TASK"]
            task_candidates = [entity for entity in exact if entity["type"] == "TASK"]
            if task_candidates:
                probabilities = model.predict_proba([feature_text(entity) for entity in task_candidates])[:, 1]
                for entity, probability in zip(task_candidates, probabilities):
                    check = semantic_quality(quality_record(record, [entity]))
                    hard_reason = hard_task_rejection(entity)
                    hard_reject = not check["passed_for_training"] or hard_reason is not None
                    strong_action = bool(STRONG_ACTION.search(str(entity.get("text", ""))))
                    if not hard_reject and (float(probability) >= THRESHOLD or strong_action):
                        candidates.append(entity)
                    else:
                        rejected.append({
                            "entity": entity,
                            "reason": hard_reason or ("semantic_quality_gate" if hard_reject else "audit30_filter_below_threshold"),
                            "keep_probability": float(probability),
                            "strong_action_override": strong_action,
                            "semantic_quality": check,
                        })
            source = "audit30_trained_conservative_v1_filter"
            source_detail = {"filter_threshold": THRESHOLD}

        # Apply the same conservative lexical gates to every source, including
        # local-LLM output. The gates only reject; they never invent a span.
        screened = []
        for entity in candidates:
            reason = hard_task_rejection(entity) if entity.get("type") == "TASK" else None
            if reason:
                rejected.append({"entity": entity, "reason": reason})
            else:
                screened.append(entity)
        candidates, non_task_rejections = sanitize_non_tasks(screened)
        rejected.extend(non_task_rejections)

        # Resolve all overlaps explicitly before exposing the single-layer view.
        entities, overlap_drops = resolve_single_layer(candidates)
        rejected.extend(overlap_drops)
        quality = semantic_quality(quality_record(record, entities))
        eligible = quality["passed_for_training"] and not overlap_report(entities)
        source_counts[source] += 1
        entity_counts.update(entity["type"] for entity in entities)
        rejected_counts.update(item["reason"] for item in rejected)
        correction_log.append({"id": record_id, "source": source, "rejected_or_resolved": rejected})
        output.append({
            "id": record_id, "source": record.get("source"), "source_split": "train",
            "thread_id": record.get("thread_id"), "turn_index": record.get("turn_index"),
            "text": record["text"], "silver_v1_annotations": record.get("text2task_annotations"),
            "silver_v2_entities": entities, "silver_v2_notes": [],
            "semantic_quality": quality, "overlaps": overlap_report(entities),
            "single_layer_eligible": eligible,
            "annotation_provenance": {
                "quality_tier": "SILVER", "human_verified": False,
                "version": "entity-v2.1.0-hybrid", "source_record_id": record_id,
                "repair_source": source, "repair_source_detail": source_detail,
                "prompt_version": "text2task-entity-v2.0.2",
                "correction_timestamp": utc_now(),
                "semantic_changes_recorded": True,
            },
        })

    write_jsonl(args.output_dir / "train.jsonl", output)
    write_jsonl(args.output_dir / "correction_log.jsonl", correction_log)
    report = {
        "status": "COMPLETED", "version": "entity-v2.1.0-hybrid", "timestamp": utc_now(),
        "records": len(output), "threads": len({row["thread_id"] for row in output}),
        "annotation_tier": "SILVER", "human_verified": False,
        "source_counts": dict(sorted(source_counts.items())),
        "entity_counts": dict(sorted(entity_counts.items())),
        "eligible_records": sum(row["single_layer_eligible"] for row in output),
        "rejected_or_resolved_counts": dict(sorted(rejected_counts.items())),
        "task_filter_diagnostic": filter_report,
        "llm_attempt": {
            "successful_rows_available": len(llm_rows), "eligible_rows_used": len(llm),
            "note": "The local full-corpus run was stopped after >4 hours because throughput was not viable; partial validated output is preserved.",
        },
        "validation_or_test_used_for_prompt_or_filter": False,
        "test_data_read_or_modified": False,
        "source_hashes": {
            "train_v1": hashlib.sha256(args.train_v1.read_bytes()).hexdigest(),
            "audit_v2": hashlib.sha256(args.audit_v2.read_bytes()).hexdigest(),
            "llm_v2": hashlib.sha256(args.llm_v2.read_bytes()).hexdigest() if args.llm_v2.is_file() else None,
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
