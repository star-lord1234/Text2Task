#!/usr/bin/env python3
"""Clean unified MailEx JSONL conservatively and write an audit report."""

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

from src.preprocessing.clean_emails import CLEANING_VERSION, SPLITS, clean_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/unified"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/cleaned"))
    parser.add_argument("--report-path", type=Path, default=Path("data/reports/cleaning_report.md"))
    return parser.parse_args()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table(headers: list[str], rows: list[list[Any]]) -> str:
    def clean(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(map(clean, headers)) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    lines.extend("| " + " | ".join(map(clean, row)) + " |" for row in rows)
    return "\n".join(lines)


def fenced(text: str, limit: int = 1_200) -> str:
    text = text if len(text) <= limit else text[: limit - 1] + "…"
    return "```text\n" + text.replace("```", "` ` `") + "\n```"


def select_examples(records_by_split: dict[str, list[dict[str, Any]]], count: int = 10) -> list[dict[str, Any]]:
    candidates = []
    for split in SPLITS:
        for record in records_by_split[split]:
            removed = [op for op in record["cleaning"]["operations"] if op["action"] == "removed"]
            if removed:
                candidates.append(record)
    candidates.sort(
        key=lambda record: (
            record["source_split"],
            record["thread_id"],
            record["turn_index"],
        )
    )
    selected = []
    seen_threads = set()
    kinds = set()
    for record in candidates:
        thread_key = (record["source_split"], record["thread_id"])
        operation_kinds = {
            op["type"] for op in record["cleaning"]["operations"] if op["action"] == "removed"
        }
        if thread_key in seen_threads:
            continue
        if operation_kinds - kinds or len(selected) < count:
            selected.append(record)
            seen_threads.add(thread_key)
            kinds.update(operation_kinds)
        if len(selected) >= count:
            break
    return selected


def make_report(
    input_dir: Path,
    output_dir: Path,
    records_by_split: dict[str, list[dict[str, Any]]],
    stats: dict[str, Any],
    hashes: dict[str, str],
) -> str:
    rows = []
    totals = Counter()
    for split in SPLITS:
        values = stats["by_split"][split]
        rows.append(
            [
                split,
                values.get("records", 0),
                values.get("alignment_reliable", 0),
                values.get("alignment_fallback_raw", 0),
                values.get("records_with_operations", 0),
                values.get("records_flagged_for_review", 0),
                values.get("records_with_quoted_context", 0),
            ]
        )
        totals.update({key: value for key, value in values.items() if isinstance(value, int)})
    rows.append(
        [
            "Total",
            totals["records"],
            totals["alignment_reliable"],
            totals["alignment_fallback_raw"],
            totals["records_with_operations"],
            totals["records_flagged_for_review"],
            totals["records_with_quoted_context"],
        ]
    )
    operation_totals = Counter()
    for values in stats["by_split"].values():
        for key, value in values.items():
            if key.startswith("operation_"):
                operation_totals[key.removeprefix("operation_")] += value
    operation_rows = [[key, value] for key, value in sorted(operation_totals.items())]
    examples = select_examples(records_by_split)
    example_sections = []
    for index, record in enumerate(examples, 1):
        removed = [op for op in record["cleaning"]["operations"] if op["action"] == "removed"]
        spans = "\n".join(
            f"- `{op['type']}` raw chars `{op['raw_char_span']}`, tokens `{op['raw_token_span']}`: "
            f"{json.dumps(op['original_text'], ensure_ascii=False)}"
            for op in removed
        )
        example_sections.append(
            f"### Example {index}: `{record['id']}`\n\n"
            f"Removed spans:\n\n{spans}\n\n"
            f"Before:\n\n{fenced(record['text_raw'])}\n\n"
            f"After:\n\n{fenced(record['text'])}"
        )
    duplicates = stats["duplicates"]

    return f"""# MailEx Conservative Cleaning Report

## Result

All **{totals['records']:,}** unified MailEx records were processed without changing split membership, record IDs, original token arrays, or MailEx event annotations. Cleaning is deterministic and token-aware; no LLM rewriting, summarization, or paraphrasing was used.

{table(['Split', 'Records', 'Reliable clean alignment', 'Raw fallback', 'With operations', 'Flagged for review', 'Quoted context'], rows)}

## Safety policy

- Original reconstructed text is retained as `text_raw`; original offsets are retained as `token_offsets_raw`.
- Cleaned text is stored separately as `text`.
- `token_offsets` remains indexed by original token position. Safely removed tokens receive `null`; retained tokens reconstruct exactly from `text`.
- All MailEx non-`O` argument labels and trigger indices are protected. A candidate overlapping any protected token is retained and flagged, never silently deleted.
- If input or clean alignment validation fails, `text` falls back to `text_raw`, original offsets are restored, and `training_text_source` is set to `text_raw`.
- High-confidence trailing legal boilerplate and explicit quoted-history blocks can be removed. Ambiguous signatures, whole-message forwards, and uncertain encoding artifacts are preserved for review.
- Quoted/forwarded evidence is stored separately in `quoted_context`, including exact raw character/token spans and whether it was removed from the clean text.
- Names, negation, punctuation, temporal expressions, and token order are never paraphrased.

## Operations

{table(['Operation and action', 'Count'], operation_rows) if operation_rows else 'No cleaning operations were detected.'}

## Duplicate analysis

- Exact raw-text duplicate groups: **{duplicates['exact_group_count']:,}** covering {duplicates['exact_record_count']:,} records.
- Conservative near-duplicate groups: **{duplicates['near_group_count']:,}** covering {duplicates['near_record_count']:,} records.
- Near-duplicate rule: token 3-gram Jaccard ≥ {duplicates['near_threshold']:.2f}, length ratio ≥ 0.75, with deterministic SimHash band candidate generation. Short emails under eight normalized words are exact-match-only.
- Candidate pairs evaluated: {duplicates['near_candidate_pair_count']:,}; verified near pairs: {duplicates['near_verified_pair_count']:,}; oversized buckets skipped: {duplicates['skipped_large_simhash_buckets']}.
- Duplicate records are annotated in `duplicate_info`; none are removed or moved between splits.

## Output integrity

{table(['Output', 'SHA-256'], [[f'{split}.jsonl', hashes[split]] for split in SPLITS])}

Cleaning version: `{CLEANING_VERSION}`. Input: `{input_dir}`. Output: `{output_dir}`.

## Before/after examples with exact removed spans

{chr(10).join(example_sections) if example_sections else 'No high-confidence automatic removals were made.'}

## Reproduction

```bash
python3 scripts/clean_mailex.py
python3 -m unittest tests/test_clean_emails.py
```
"""


def main() -> None:
    args = parse_args()
    records_by_split, stats = clean_dataset(args.input_dir, args.output_dir)
    hashes = {split: sha256_path(args.output_dir / f"{split}.jsonl") for split in SPLITS}
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(
        make_report(
            args.input_dir.resolve(),
            args.output_dir.resolve(),
            records_by_split,
            stats,
            hashes,
        ),
        encoding="utf-8",
    )
    print("MailEx cleaning complete")
    for split in SPLITS:
        values = stats["by_split"][split]
        print(
            f"  {split}: {values['records']:,} records; "
            f"{values.get('alignment_fallback_raw', 0):,} raw fallbacks; "
            f"{values.get('records_flagged_for_review', 0):,} flagged"
        )
    print(
        f"  Exact duplicate groups: {stats['duplicates']['exact_group_count']:,}; "
        f"near-duplicate groups: {stats['duplicates']['near_group_count']:,}"
    )
    print(f"  Output: {args.output_dir.resolve()}")
    print(f"  Report: {args.report_path.resolve()}")


if __name__ == "__main__":
    main()
