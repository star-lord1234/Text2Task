#!/usr/bin/env python3
"""Build balanced, type-valid Text2Task relation-classification pairs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_data.relation_classification import prepare_all_splits  # noqa: E402
from src.model_data.reporting import write_model_data_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/final"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/model_ready/relations"))
    parser.add_argument("--entities-dir", type=Path, default=Path("data/model_ready/entities"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/model_data_statistics.md"))
    parser.add_argument("--negative-ratio", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--entity-source", choices=("annotated", "gold", "predicted"), default="annotated")
    parser.add_argument("--predicted-train", type=Path)
    parser.add_argument("--predicted-validation", type=Path)
    parser.add_argument("--predicted-test", type=Path)
    parser.add_argument("--samples", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    predicted_files = None
    if args.entity_source == "predicted":
        predicted_files = {
            "train": args.predicted_train,
            "validation": args.predicted_validation,
            "test": args.predicted_test,
        }
        missing = [split for split, path in predicted_files.items() if path is None or not path.is_file()]
        if missing:
            raise SystemExit(f"Predicted entity source requires existing files for: {', '.join(missing)}")
    stats = prepare_all_splits(
        args.input_dir,
        args.output_dir,
        negative_ratio=args.negative_ratio,
        seed=args.seed,
        entity_source=args.entity_source,
        predicted_entity_files=predicted_files,
    )
    write_model_data_report(args.report, args.entities_dir, args.output_dir)
    print("Transformer relation-classification data")
    for split, values in stats["splits"].items():
        print(
            f"  {split}: {values['model_rows']} rows = {values['positive_rows']} positive + "
            f"{values['negative_rows']} NONE; labels={values['label_counts']}"
        )
    print("\nSample training records")
    with (args.output_dir / "train.jsonl").open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    examples = []
    for desired in ("DEPENDS_ON", "ASSIGNED_TO", "NONE", "DUE_ON", "SCHEDULED_ON"):
        match = next((row for row in rows if row["label"] == desired), None)
        if match is not None:
            examples.append(match)
    for row in examples[: max(0, args.samples)]:
        print(json.dumps({
            "id": row["id"],
            "source_record_id": row["source_record_id"],
            "thread_id": row["thread_id"],
            "source_entity": row["source_entity"],
            "target_entity": row["target_entity"],
            "candidate_relation_types": row["candidate_relation_types"],
            "label": row["label"],
            "relation_evidence": row["relation_evidence"],
            "marked_text": row["marked_text"][:600],
        }, ensure_ascii=False, indent=2))
    print(f"Output: {args.output_dir.resolve()}")
    print(f"Report: {args.report.resolve()}")


if __name__ == "__main__":
    main()
