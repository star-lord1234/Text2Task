#!/usr/bin/env python3
"""Create resumable local-LLM SILVER-v2 TASK/PERSON/TEMPORAL annotations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.annotation.llm_annotator import OllamaProvider, ProviderError, PromptBuilder  # noqa: E402
from src.annotation.semantic_quality import semantic_quality, spans_overlap  # noqa: E402


PROMPT_VERSION_RE = re.compile(r"prompt_version:\s*([^\s]+)")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def ids_in(path: Path, key: str = "id") -> set[str]:
    if not path.is_file():
        return set()
    return {row[key] for row in read_jsonl(path) if isinstance(row.get(key), str)}


def render_prompt(template: str, text: str) -> str:
    # The exact surface form is sufficient for deterministic offset recovery
    # when it occurs once. Avoiding a per-character guide cuts local inference
    # latency substantially; every recovered offset is still recorded.
    return template.replace("{{EMAIL_TEXT}}", text).replace("{{OFFSET_GUIDE}}", "")


def normalize_prediction(raw: Any, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("entities"), list) or not isinstance(raw.get("notes"), list):
        raise ValueError("root must contain entities and notes arrays")
    entities, corrections, errors = [], [], []
    seen = set()
    for index, entity in enumerate(raw["entities"]):
        if not isinstance(entity, dict):
            errors.append(f"entities[{index}] is not an object")
            continue
        entity_type = entity.get("type")
        surface = entity.get("text")
        start, end = entity.get("start"), entity.get("end")
        if entity_type not in {"TASK", "PERSON", "TEMPORAL"} or not isinstance(surface, str) or not surface:
            errors.append(f"entities[{index}] has invalid type/text")
            continue
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)) or text[start:end] != surface:
            occurrences = [(match.start(), match.end(), "exact") for match in re.finditer(re.escape(surface), text)]
            if not occurrences:
                occurrences = [
                    (match.start(), match.end(), "case_insensitive")
                    for match in re.finditer(re.escape(surface), text, flags=re.IGNORECASE)
                ]
            if len(occurrences) == 1:
                prior = {"start": start, "end": end, "surface": surface}
                start, end, method = occurrences[0]
                surface = text[start:end]
                corrections.append({
                    "entity_index": index,
                    "type": "unique_surface_offset_correction",
                    "method": method,
                    "from": prior,
                    "to": {"start": start, "end": end, "surface": surface},
                })
            else:
                errors.append(f"entities[{index}] offset mismatch and surface occurs {len(occurrences)} times")
                continue
        signature = (entity_type, start, end)
        if signature in seen:
            errors.append(f"entities[{index}] duplicates {signature}")
            continue
        seen.add(signature)
        entities.append({
            "id": f"v2-e{len(entities) + 1}",
            "type": entity_type,
            "text": surface,
            "start": start,
            "end": end,
            "negated": bool(entity.get("negated", False)) if entity_type == "TASK" else False,
            "ambiguous": bool(entity.get("ambiguous", False)),
        })
    entities.sort(key=lambda value: (value["start"], value["end"], value["type"]))
    return entities, corrections, errors


def quality_record(record: dict[str, Any], entities: list[dict[str, Any]]) -> dict[str, Any]:
    canonical = []
    for entity in entities:
        value = dict(entity)
        if value["type"] == "TASK":
            value["task_attributes"] = {
                "operation": "CREATE", "status": "PENDING", "negated": bool(value.get("negated", False)),
                "ambiguous": bool(value.get("ambiguous", False)), "identity_status": "LOCAL_ONLY",
            }
        else:
            value["task_attributes"] = None
        canonical.append(value)
    return {"text": record["text"], "text2task_annotations": {"entities": canonical}}


def overlap_report(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlaps = []
    for index, left in enumerate(entities):
        for right in entities[index + 1:]:
            if spans_overlap(left, right):
                overlaps.append({"left": left["id"], "right": right["id"], "left_type": left["type"], "right_type": right["type"]})
    return overlaps


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/candidates/train.jsonl"))
    parser.add_argument("--v1", type=Path, default=Path("data/final/train.jsonl"))
    parser.add_argument("--prompt", type=Path, default=Path("configs/entity_annotation_prompt_v2.md"))
    parser.add_argument("--schema", type=Path, default=Path("configs/text2task_entity_schema_v2.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/annotations/silver_v2_entities_v202"))
    parser.add_argument("--model", default="llama3.1:latest")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-bulk", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if (args.limit is None or args.limit > 20) and not args.allow_bulk:
        raise SystemExit("Use --limit <=20 for a pilot or --allow-bulk after inspecting it")
    candidates = read_jsonl(args.input)
    if any(record.get("source_split") != "train" for record in candidates):
        raise SystemExit("SILVER-v2 prompt input must contain original training records only")
    v1 = {record["id"]: record.get("text2task_annotations") for record in read_jsonl(args.v1)}
    template = args.prompt.read_text(encoding="utf-8")
    match = PROMPT_VERSION_RE.search(template)
    if not match:
        raise SystemExit("prompt version marker missing")
    prompt_version = match.group(1)
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    success_path = args.output_dir / "train.jsonl"
    failure_path = args.output_dir / "failed.jsonl"
    checkpoint_path = args.output_dir / "checkpoint.json"
    report_path = args.output_dir / "report.json"
    successful = ids_in(success_path)
    failed = ids_in(failure_path, "source_record_id")
    provider = OllamaProvider(args.model, timeout=args.timeout, format_mode="schema", max_output_tokens=512, context_window=4096)
    counts = Counter()
    usage = Counter()
    considered = 0
    started = utc_now()
    for record in candidates:
        record_id = record["id"]
        if record_id in successful:
            counts["skipped_success"] += 1
            continue
        if record_id in failed and not args.retry_failed:
            counts["skipped_failed"] += 1
            continue
        if args.limit is not None and considered >= args.limit:
            break
        considered += 1
        attempts = []
        final_error = None
        for attempt in range(1, args.max_attempts + 1):
            try:
                response = provider.generate(render_prompt(template, record["text"]), schema)
                usage["input_tokens"] += response.usage.input_tokens or 0
                usage["output_tokens"] += response.usage.output_tokens or 0
                raw = json.loads(response.content)
                entities, corrections, errors = normalize_prediction(raw, record["text"])
                if errors:
                    raise ValueError("; ".join(errors))
                quality = semantic_quality(quality_record(record, entities))
                overlaps = overlap_report(entities)
                trainable = quality["passed_for_training"] and not overlaps
                output = {
                    "id": record_id,
                    "source": record.get("source"),
                    "source_split": record["source_split"],
                    "thread_id": record.get("thread_id"),
                    "turn_index": record.get("turn_index"),
                    "text": record["text"],
                    "silver_v1_annotations": v1.get(record_id),
                    "silver_v2_entities": entities,
                    "silver_v2_notes": raw.get("notes", []),
                    "semantic_quality": quality,
                    "overlaps": overlaps,
                    "single_layer_eligible": trainable,
                    "annotation_provenance": {
                        "quality_tier": "SILVER", "human_verified": False,
                        "provider": "ollama", "model": response.model,
                        "prompt_version": prompt_version, "schema_version": "entity-v2.0.0",
                        "timestamp": utc_now(), "source_record_id": record_id,
                        "attempt": attempt, "structural_corrections": corrections,
                        "raw_response_sha256": hashlib.sha256(response.content.encode()).hexdigest(),
                    },
                }
                append_jsonl(success_path, output)
                successful.add(record_id)
                counts["successful"] += 1
                counts["trainable"] += int(trainable)
                counts["semantic_quarantine"] += int(not quality["passed_for_training"])
                counts["overlap_quarantine"] += int(bool(overlaps))
                counts["empty_task"] += int(not any(entity["type"] == "TASK" for entity in entities))
                counts["offset_corrections"] += len(corrections)
                final_error = None
                break
            except (ProviderError, json.JSONDecodeError, ValueError) as error:
                final_error = str(error)
                attempts.append({"attempt": attempt, "error": str(error), "timestamp": utc_now()})
        if final_error is not None:
            append_jsonl(failure_path, {
                "source_record_id": record_id, "source_split": record["source_split"],
                "provider": "ollama", "model": args.model, "prompt_version": prompt_version,
                "attempt_history": attempts, "failure": final_error,
            })
            failed.add(record_id)
            counts["failed"] += 1
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(json.dumps({
            "updated_at": utc_now(), "last_record_id": record_id,
            "counts": dict(counts), "usage": dict(usage),
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "status": "COMPLETED", "started_at": started, "completed_at": utc_now(),
        "input": str(args.input), "provider": "ollama", "model": args.model,
        "prompt_version": prompt_version, "schema_version": "entity-v2.0.0",
        "human_verified": False, "annotation_tier": "SILVER",
        "records_considered": considered, "counts": dict(counts), "usage": dict(usage),
        "test_records_used_as_prompt_examples": False,
        "validation_records_used_as_prompt_examples": False,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
