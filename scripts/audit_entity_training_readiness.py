#!/usr/bin/env python3
"""Audit Text2Task entity-model data before any DistilBERT fine-tuning."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_data.entity_readiness import audit_entity_data, write_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity-dir", type=Path, default=Path("data/model_ready/entities"))
    parser.add_argument("--final-dir", type=Path, default=Path("data/final"))
    parser.add_argument("--schema", type=Path, default=Path("configs/text2task_schema_v1.json"))
    parser.add_argument("--vocab", type=Path, default=Path("configs/tokenizers/distilbert-base-uncased-vocab.txt"))
    parser.add_argument("--json-report", type=Path, default=Path("data/reports/entity_training_readiness.json"))
    parser.add_argument("--markdown-report", type=Path, default=Path("data/reports/entity_training_readiness.md"))
    parser.add_argument("--context-limit", type=int, default=512)
    parser.add_argument("--minimum-train-spans", type=int, default=20)
    parser.add_argument("--minimum-evaluation-spans", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = audit_entity_data(
        args.entity_dir,
        args.final_dir,
        args.schema,
        vocab_path=args.vocab,
        context_limit=args.context_limit,
        minimum_train_spans=args.minimum_train_spans,
        minimum_evaluation_spans=args.minimum_evaluation_spans,
    )
    write_report(audit, args.json_report, args.markdown_report)
    print(f"Entity training readiness: {audit['status']}")
    print(f"  Structurally valid for SILVER experiments: {audit['structurally_valid_for_silver_experiments']}")
    print(f"  Ready for training with gold evaluation: {audit['ready_for_training_with_gold_evaluation']}")
    for split in ("train", "validation", "test"):
        values = audit["split_reports"][split]
        print(
            f"  {split}: {values['emails']} emails, {values['model_rows']} rows, "
            f"tiers={values['annotation_tiers_by_email']}, max_tokens={values['token_lengths_with_special_tokens']['maximum']}"
        )
    print(f"  Structural errors: {len(audit['structural_errors'])}")
    print(f"  Insufficient-support flags: {len(audit['insufficient_label_support'])}")
    for item in audit["insufficient_label_support"]:
        print(f"    {item['label']} / {item['split']}: {item['count']} < {item['threshold']}")
    print(f"  Markdown: {args.markdown_report.resolve()}")
    print(f"  JSON: {args.json_report.resolve()}")


if __name__ == "__main__":
    main()
