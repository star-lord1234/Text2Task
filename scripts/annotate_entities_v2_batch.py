#!/usr/bin/env python3
"""Batch local-LLM entity-v2 annotation with per-record validation/quarantine."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.annotate_entities_v2 import (  # noqa: E402
    append_jsonl, ids_in, normalize_prediction, overlap_report, quality_record,
    read_jsonl, utc_now,
)
from src.annotation.llm_annotator import OllamaProvider, ProviderError  # noqa: E402
from src.annotation.semantic_quality import semantic_quality  # noqa: E402


PROMPT_VERSION = "text2task-entity-v2.1.0-batch"


def output_schema() -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False, "required": ["records"],
        "properties": {"records": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "entities", "notes"],
            "properties": {
                "id": {"type": "string"},
                "entities": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["type", "text", "start", "end", "negated", "ambiguous"],
                    "properties": {
                        "type": {"enum": ["TASK", "PERSON", "TEMPORAL"]},
                        "text": {"type": "string", "minLength": 1},
                        "start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 1},
                        "negated": {"type": "boolean"}, "ambiguous": {"type": "boolean"},
                    },
                }},
                "notes": {"type": "array", "items": {"type": "string"}},
            },
        }}},
    }


def prompt(records: list[dict[str, Any]]) -> str:
    blocks = []
    for record in records:
        blocks.append(f"<EMAIL id={json.dumps(record['id'])}>\n{record['text']}\n</EMAIL>")
    return """Return JSON only with one output record for every EMAIL id.
For each email annotate exact-substring TASK, PERSON, TEMPORAL entities. Offsets
are zero-based within that email. Empty entities are valid.

TASK is only a current request, future commitment, prohibition, or concrete
planned action. Historical/completed events, descriptions, system/facility
states, attached-document statements, topics, greetings, and advertisements are
not TASK. Keep the smallest complete predicate and object; no nested duplicates;
exclude detachable dates and owners. Preserve negation/modality.
PERSON is an explicit personal name only. TEMPORAL is an explicit date, time,
duration, or relative time. Never invent entities.

Audit lessons: `was filed`, `called last week`, `have signed`, `has moved`,
`were disrupted`, `rejected`, `will remain closed`, and `is attached` are not new
TASKs. `send the report`, `must be reviewed`, `investigate`, `do not insert`,
`reserve this time`, and `let me know how to proceed` are TASKs.

""" + "\n\n".join(blocks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/candidates/train.jsonl"))
    parser.add_argument("--v1", type=Path, default=Path("data/final/train.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/annotations/silver_v2_entities"))
    parser.add_argument("--model", default="llama3.1:latest")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--limit-records", type=int)
    parser.add_argument("--timeout", type=float, default=300)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = read_jsonl(args.input)
    if any(record.get("source_split") != "train" for record in candidates):
        raise SystemExit("Only original train records may be annotated")
    v1 = {record["id"]: record.get("text2task_annotations") for record in read_jsonl(args.v1)}
    success_path, failure_path = args.output_dir / "train.jsonl", args.output_dir / "failed.jsonl"
    successful, failed = ids_in(success_path), ids_in(failure_path, "source_record_id")
    remaining = [record for record in candidates if record["id"] not in successful | failed]
    if args.limit_records is not None:
        remaining = remaining[:args.limit_records]
    provider = OllamaProvider(args.model, timeout=args.timeout, format_mode="schema", max_output_tokens=2048, context_window=8192)
    counts, usage = Counter(), Counter()
    started = utc_now()
    for batch_start in range(0, len(remaining), args.batch_size):
        batch = remaining[batch_start:batch_start + args.batch_size]
        by_id = {record["id"]: record for record in batch}
        try:
            response = provider.generate(prompt(batch), output_schema())
            usage["input_tokens"] += response.usage.input_tokens or 0
            usage["output_tokens"] += response.usage.output_tokens or 0
            raw = json.loads(response.content)
            returned = {item.get("id"): item for item in raw.get("records", []) if isinstance(item, dict)}
        except (ProviderError, json.JSONDecodeError, ValueError) as error:
            returned = {}
            batch_error = str(error)
        else:
            batch_error = None
        for record_id, record in by_id.items():
            item = returned.get(record_id)
            try:
                if item is None:
                    raise ValueError(batch_error or "provider omitted record from batch")
                entities, corrections, errors = normalize_prediction(item, record["text"])
                if errors:
                    raise ValueError("; ".join(errors))
                quality = semantic_quality(quality_record(record, entities))
                overlaps = overlap_report(entities)
                trainable = quality["passed_for_training"] and not overlaps
                append_jsonl(success_path, {
                    "id": record_id, "source": record.get("source"), "source_split": "train",
                    "thread_id": record.get("thread_id"), "turn_index": record.get("turn_index"),
                    "text": record["text"], "silver_v1_annotations": v1.get(record_id),
                    "silver_v2_entities": entities, "silver_v2_notes": item.get("notes", []),
                    "semantic_quality": quality, "overlaps": overlaps,
                    "single_layer_eligible": trainable,
                    "annotation_provenance": {
                        "quality_tier": "SILVER", "human_verified": False, "provider": "ollama",
                        "model": response.model, "prompt_version": PROMPT_VERSION,
                        "schema_version": "entity-v2.0.0", "timestamp": utc_now(),
                        "source_record_id": record_id, "batch_size": len(batch),
                        "structural_corrections": corrections,
                        "raw_response_sha256": hashlib.sha256(response.content.encode()).hexdigest(),
                    },
                })
                counts["successful"] += 1
                counts["trainable"] += int(trainable)
                counts["semantic_quarantine"] += int(not quality["passed_for_training"])
                counts["overlap_quarantine"] += int(bool(overlaps))
                counts["empty_task"] += int(not any(entity["type"] == "TASK" for entity in entities))
                counts["offset_corrections"] += len(corrections)
            except ValueError as error:
                append_jsonl(failure_path, {
                    "source_record_id": record_id, "source_split": "train", "provider": "ollama",
                    "model": args.model, "prompt_version": PROMPT_VERSION,
                    "failure": str(error), "batch_start": batch_start,
                })
                counts["failed"] += 1
        (args.output_dir / "checkpoint.json").write_text(json.dumps({
            "updated_at": utc_now(), "processed_this_run": min(batch_start + len(batch), len(remaining)),
            "remaining_at_start": len(remaining), "counts": dict(counts), "usage": dict(usage),
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "status": "COMPLETED", "started_at": started, "completed_at": utc_now(),
        "provider": "ollama", "model": args.model, "prompt_version": PROMPT_VERSION,
        "schema_version": "entity-v2.0.0", "annotation_tier": "SILVER",
        "human_verified": False, "records_considered": len(remaining),
        "counts": dict(counts), "usage": dict(usage), "batch_size": args.batch_size,
        "validation_records_used_as_prompt_examples": False,
        "test_records_used_as_prompt_examples": False,
    }
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
