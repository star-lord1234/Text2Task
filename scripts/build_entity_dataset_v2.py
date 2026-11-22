#!/usr/bin/env python3
"""Assemble versioned, single-layer three-entity SILVER-v2 model data."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_data.token_classification import DistilBertWordPieceTokenizer, prepare_record  # noqa: E402


LABELS = ["O", "B-TASK", "I-TASK", "B-PERSON", "I-PERSON", "B-TEMPORAL", "I-TEMPORAL"]
TYPE_PRIORITY = {"PERSON": 0, "TEMPORAL": 1, "TASK": 2}
SEED = 20261101


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return int(left["start"]) < int(right["end"]) and int(right["start"]) < int(left["end"])


def resolve_single_layer(entities: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Shortest exact span wins; PERSON, then TEMPORAL, then TASK breaks ties."""

    candidates = [deepcopy(entity) for entity in entities if entity.get("type") in TYPE_PRIORITY]
    ordered = sorted(
        candidates,
        key=lambda entity: (
            int(entity["end"]) - int(entity["start"]),
            TYPE_PRIORITY[str(entity["type"])],
            int(entity["start"]),
            int(entity["end"]),
            str(entity.get("id", "")),
        ),
    )
    kept, dropped = [], []
    for entity in ordered:
        conflict = next((existing for existing in kept if overlaps(entity, existing)), None)
        if conflict is None:
            kept.append(entity)
        else:
            dropped.append({
                "entity": entity,
                "reason": "single_layer_overlap",
                "kept_entity_id": conflict.get("id"),
                "policy": "shortest_span_then_PERSON_TEMPORAL_TASK",
            })
    kept.sort(key=lambda entity: (int(entity["start"]), int(entity["end"]), str(entity["type"])))
    for index, entity in enumerate(kept, 1):
        entity["id"] = f"v2-e{index}"
        entity.pop("task_attributes", None)
        entity.pop("negated", None)
        entity.pop("ambiguous", None)
    return kept, dropped


def model_record(base: dict[str, Any], entities: list[dict[str, Any]], provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": base["id"],
        "source": base.get("source", "mailex"),
        "source_split": base["source_split"],
        "thread_id": base.get("thread_id"),
        "turn_index": base.get("turn_index"),
        "text": base["text"],
        "text2task_annotations": {"entities": entities, "relations": [], "unresolved": []},
        "annotation_provenance": provenance,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-v2", type=Path, default=Path("data/annotations/silver_v2_hybrid/train.jsonl"))
    parser.add_argument("--audit-v2", type=Path, default=Path("data/diagnostics/entity_pipeline/audit30_corrected_silver_v2.jsonl"))
    parser.add_argument("--train-v1", type=Path, default=Path("data/final/train.jsonl"))
    parser.add_argument("--validation-v1", type=Path, default=Path("data/final/validation.jsonl"))
    parser.add_argument("--output-records", type=Path, default=Path("data/silver_v2/entities_three_class"))
    parser.add_argument("--output-model", type=Path, default=Path("data/model_ready/entities_v2_three_class"))
    parser.add_argument("--vocab", type=Path, default=Path("configs/tokenizers/distilbert-base-uncased-vocab.txt"))
    parser.add_argument("--minimum-train-records", type=int, default=250)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train_v1_rows = read_jsonl(args.train_v1)
    validation_v1_rows = read_jsonl(args.validation_v1)
    train_v1 = {row["id"]: row for row in train_v1_rows}
    llm_rows = read_jsonl(args.llm_v2)
    llm = {row["id"]: row for row in llm_rows if row.get("single_layer_eligible")}
    audit_rows = read_jsonl(args.audit_v2)
    # Only the 20 explicitly clean single-layer audit records are eligible.
    diagnostic_ids = {row["id"] for row in read_jsonl(Path("data/diagnostics/entity_pipeline/three_class_20_annotations.jsonl"))}
    audit = {row["id"]: row for row in audit_rows if row["id"] in diagnostic_ids}

    train_records, resolution_log = [], []
    for record_id in sorted(set(llm) | set(audit)):
        base = train_v1[record_id]
        if record_id in audit:
            source_entities = audit[record_id]["corrected_silver_v2_diagnostic"]["entities"]
            provenance = {
                "quality_tier": "SILVER", "human_verified": False,
                "version": "entity-v2.0.0", "source": "diagnostic_audit_reference",
                "source_record_id": record_id,
            }
        else:
            source_entities = llm[record_id]["silver_v2_entities"]
            provenance = deepcopy(llm[record_id]["annotation_provenance"])
            provenance.update({"quality_tier": "SILVER", "human_verified": False, "version": "entity-v2.0.0"})
        entities, dropped = resolve_single_layer(source_entities)
        if dropped:
            resolution_log.append({"source_record_id": record_id, "dropped": dropped})
        train_records.append(model_record(base, entities, provenance))

    if len(train_records) < args.minimum_train_records:
        raise SystemExit(f"Only {len(train_records)} trainable v2 records; require at least {args.minimum_train_records}")

    validation_records = []
    for base in validation_v1_rows:
        source_entities = (base.get("text2task_annotations") or {}).get("entities", [])
        entities, dropped = resolve_single_layer(source_entities)
        if dropped:
            resolution_log.append({"source_record_id": base["id"], "split": "validation", "dropped": dropped})
        validation_records.append(model_record(base, entities, {
            "quality_tier": "SILVER", "human_verified": False,
            "version": "v1-held-out-provisional-three-class-view",
            "source_record_id": base["id"],
        }))

    write_jsonl(args.output_records / "train.jsonl", train_records)
    write_jsonl(args.output_records / "validation.jsonl", validation_records)
    write_jsonl(args.output_records / "overlap_resolution_log.jsonl", resolution_log)

    tokenizer = DistilBertWordPieceTokenizer(args.vocab)
    statistics: dict[str, Any] = {"splits": {}}
    for split, records in (("train", train_records), ("validation", validation_records)):
        rows, entity_counts = [], Counter()
        for record in records:
            prepared, info = prepare_record(record, tokenizer, final_split=split, max_length=512, stride=64)
            if info["layers"] != 1:
                raise ValueError(f"{record['id']}: v2 view produced {info['layers']} layers")
            rows.extend(prepared)
            entity_counts.update(entity["type"] for entity in record["text2task_annotations"]["entities"])
        write_jsonl(args.output_model / f"{split}.jsonl", rows)
        statistics["splits"][split] = {
            "source_records": len(records), "model_rows": len(rows),
            "threads": len({record["thread_id"] for record in records}),
            "entity_counts": dict(sorted(entity_counts.items())),
            "annotation_tiers": dict(Counter(record["annotation_provenance"]["quality_tier"] for record in records)),
        }
    train_threads = {record["thread_id"] for record in train_records}
    validation_threads = {record["thread_id"] for record in validation_records}
    overlap = sorted(train_threads & validation_threads)
    if overlap:
        raise ValueError(f"cross-split thread overlap: {overlap[:10]}")
    statistics.update({
        "version": "entity-v2.0.0", "seed": SEED,
        "entity_types": ["TASK", "PERSON", "TEMPORAL"], "bio_labels": LABELS,
        "single_layer": True,
        "overlap_policy": "shortest span wins; ties PERSON then TEMPORAL then TASK; every dropped span logged",
        "train_validation_thread_overlap": [],
        "test_data_read_or_modified": False,
        "human_gold_records": 0,
        "llm_success_records": len(llm_rows),
        "llm_trainable_records": len(llm),
        "audit_reference_overrides": len(audit),
        "source_hashes": {
            "train_v1": hashlib.sha256(args.train_v1.read_bytes()).hexdigest(),
            "validation_v1": hashlib.sha256(args.validation_v1.read_bytes()).hexdigest(),
            "llm_v2": hashlib.sha256(args.llm_v2.read_bytes()).hexdigest(),
        },
    })
    args.output_model.mkdir(parents=True, exist_ok=True)
    (args.output_model / "label_map.json").write_text(json.dumps({
        "labels": LABELS, "label_to_id": {label: i for i, label in enumerate(LABELS)},
        "id_to_label": {str(i): label for i, label in enumerate(LABELS)}, "ignore_index": -100,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_model / "statistics.json").write_text(json.dumps(statistics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(statistics, indent=2))


if __name__ == "__main__":
    main()
