#!/usr/bin/env python3
"""Create and summarize a deterministic, non-GOLD SILVER-v2 quality audit."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


SEED = 20261102
RATINGS = {"acceptable", "minor", "major"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=Path("data/annotations/silver_v2_entities_v202/train.jsonl"))
    parser.add_argument("--original-audit", type=Path, default=Path("data/diagnostics/entity_pipeline/audit30_corrected_silver_v2.jsonl"))
    parser.add_argument("--decisions", type=Path, default=Path("data/reports/silver_v2_audit30_decisions.json"))
    parser.add_argument("--output-jsonl", type=Path, default=Path("data/reports/silver_v2_audit30.jsonl"))
    parser.add_argument("--output-md", type=Path, default=Path("data/reports/silver_v2_audit30.md"))
    parser.add_argument("--sample-size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=SEED)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_jsonl(args.annotations)
    excluded = {row["id"] for row in read_jsonl(args.original_audit)}
    eligible = sorted((row for row in rows if row["id"] not in excluded), key=lambda row: row["id"])
    if len(eligible) < args.sample_size:
        raise SystemExit(f"Need {args.sample_size} post-v2 records outside the original audit; found {len(eligible)}")
    sample = random.Random(args.seed).sample(eligible, args.sample_size)
    sample.sort(key=lambda row: row["id"])
    decisions = json.loads(args.decisions.read_text(encoding="utf-8")) if args.decisions.is_file() else {}
    output = []
    for row in sample:
        decision = decisions.get(row["id"], {})
        rating = decision.get("rating", "pending")
        if rating != "pending" and rating not in RATINGS:
            raise ValueError(f"{row['id']}: invalid rating {rating}")
        v1 = row.get("silver_v1_annotations") or {}
        output.append({
            "id": row["id"], "source_split": row["source_split"], "thread_id": row.get("thread_id"),
            "text": row["text"],
            "silver_v1_entities": [entity for entity in v1.get("entities", []) if entity.get("type") in {"TASK", "PERSON", "TEMPORAL"}],
            "silver_v2_entities": row["silver_v2_entities"],
            "automatic_semantic_quality": row["semantic_quality"],
            "single_layer_eligible": row["single_layer_eligible"],
            "inspection": {
                "rating": rating,
                "notes": decision.get("notes", ""),
                "reviewer_type": "AI-assisted manual inspection",
                "human_verified": False,
                "creates_gold": False,
            },
        })
    write_jsonl(args.output_jsonl, output)
    counts = Counter(row["inspection"]["rating"] for row in output)
    entity_counts = Counter(entity["type"] for row in output for entity in row["silver_v2_entities"])
    lines = [
        "# SILVER v2 deterministic 30-record quality audit", "",
        f"Seed: `{args.seed}`. The sample excludes all 30 records used to create the v2 rules.",
        "This is AI-assisted manual inspection, not independent human verification and not GOLD.", "",
        "## Summary", "",
        f"- Records: {len(output)}", f"- Ratings: {dict(sorted(counts.items()))}",
        f"- v2 entities in sample: {dict(sorted(entity_counts.items()))}",
        "- SILVER-v1 comparison: 22 major, 6 minor, 2 acceptable in the original diagnostic audit.", "",
        "## Records", "",
    ]
    for row in output:
        spans = "; ".join(f"{entity['type']}={entity['text']!r}" for entity in row["silver_v2_entities"]) or "(none)"
        lines.extend([
            f"### {row['id']}", "",
            f"Rating: **{row['inspection']['rating']}** — {row['inspection']['notes'] or 'pending inspection'}", "",
            f"V2 spans: {spans}", "",
            f"> {row['text'].replace(chr(10), ' ')}", "",
        ])
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(output), "ratings": dict(counts), "entity_counts": dict(entity_counts)}, indent=2))


if __name__ == "__main__":
    main()
