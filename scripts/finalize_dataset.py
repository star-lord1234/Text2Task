#!/usr/bin/env python3
"""Assemble leak-free Text2Task splits from reviewed GOLD and valid SILVER."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.annotation.finalize_dataset import FinalizerConfig, assemble_dataset, format_summary  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleaned-dir", type=Path, default=Path("data/cleaned"))
    parser.add_argument("--gold-dir", type=Path, default=Path("data/annotations/gold"))
    parser.add_argument(
        "--silver",
        type=Path,
        action="append",
        default=None,
        help="Silver JSONL; repeatable. Defaults to reviewed train/dev/test plus raw LLM split files.",
    )
    parser.add_argument("--rejected-dir", type=Path, default=Path("data/annotations/rejected"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/final"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/final_dataset_statistics.md"))
    parser.add_argument("--integrity", type=Path, default=Path("data/reports/split_integrity.json"))
    parser.add_argument("--small-test-threshold", type=int, default=5)
    parser.add_argument(
        "--allow-silver-evaluation",
        action="store_true",
        help="Explicitly allow AI-generated SILVER in validation/test; metrics are not human-gold evaluation",
    )
    return parser.parse_args()


def default_silver_paths() -> list[Path]:
    paths = [Path("data/annotations/silver_reviewed") / f"{split}.jsonl" for split in ("train", "dev", "test")]
    # Raw provider silver follows the same split filename convention. Prompt
    # dumps and checkpoints are never globbed or interpreted as annotations.
    paths.extend(path for path in (Path("data/annotations/silver") / f"{split}.jsonl" for split in ("train", "dev", "test")) if path.is_file())
    paths.extend(path for path in (Path("data/annotations/silver_auto") / f"{split}.jsonl" for split in ("train", "dev", "test")) if path.is_file())
    return paths


def main() -> None:
    args = parse_args()
    if args.small_test_threshold < 1:
        raise SystemExit("--small-test-threshold must be positive")
    for split in ("train", "dev", "test"):
        cleaned = args.cleaned_dir / f"{split}.jsonl"
        if not cleaned.is_file():
            raise SystemExit(f"Missing cleaned split: {cleaned}")
    integrity = assemble_dataset(
        FinalizerConfig(
            cleaned_dir=args.cleaned_dir,
            gold_dir=args.gold_dir,
            silver_paths=args.silver or default_silver_paths(),
            rejected_dir=args.rejected_dir,
            output_dir=args.output_dir,
            report_path=args.report,
            integrity_path=args.integrity,
            small_test_threshold=args.small_test_threshold,
            allow_silver_evaluation=args.allow_silver_evaluation,
        )
    )
    print(format_summary(integrity))
    print(f"  Final data: {args.output_dir.resolve()}")
    print(f"  Statistics: {args.report.resolve()}")
    print(f"  Integrity: {args.integrity.resolve()}")
    if not integrity["ready_for_ml"]:
        print("  Dataset was not marked complete; resolve blocking issues and rerun.")


if __name__ == "__main__":
    main()
