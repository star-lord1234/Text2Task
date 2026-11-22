#!/usr/bin/env python3
"""Generate conservative Text2Task SILVER annotations for selected MailEx records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.annotation.auto_silver import annotate_jsonl  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/candidates"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/annotations/silver_auto"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/auto_silver_report.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reports = []
    for split in ("train", "dev", "test"):
        input_path = args.input_dir / f"{split}.jsonl"
        if not input_path.is_file():
            raise SystemExit(f"Missing candidate split: {input_path}")
        report = annotate_jsonl(input_path, args.output_dir / f"{split}.jsonl")
        report["split"] = split
        reports.append(report)
        print(
            f"{split}: records={report['valid_outputs']}/{report['input_records']} tasks={report.get('tasks', 0)} "
            f"entities={report.get('entities', 0)} relations={report.get('relations', 0)} "
            f"dependencies={report.get('dependencies', 0)} validation_failures={len(report['validation_failures'])}"
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"runs": reports}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if any(report["validation_failures"] for report in reports):
        raise SystemExit("Some generated annotations failed validation; inspect the report before final assembly")


if __name__ == "__main__":
    main()
