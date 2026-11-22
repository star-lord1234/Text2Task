#!/usr/bin/env python3
"""Score a validation_predictions.jsonl with strict, lenient, and token-level metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_training.span_metrics import evaluate, format_table  # noqa: E402

ENTITY_TYPES = ["TASK", "PERSON", "TEMPORAL"]


def score_file(path: Path, iou_threshold: float = 0.5) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = evaluate([r["predictions"] for r in rows], [r["references"] for r in rows], ENTITY_TYPES, iou_threshold)
    result["rows"] = len(rows)
    result["source"] = str(path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path, nargs="+")
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--out", type=Path, help="write JSON results here")
    args = parser.parse_args()
    results = {}
    for path in args.predictions:
        result = score_file(path, args.iou)
        results[str(path)] = result
        print(f"\n## {path}\n")
        print(format_table(result))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
