#!/usr/bin/env python3
"""Convert MailEx train/dev/test into a unified, turn-level JSONL format.

The converter is intentionally lossless with respect to the annotated JSON:
original token arrays and per-turn MailEx events are copied verbatim.  Optional
sender/recipient/timestamp/subject values are taken only from confidently
aligned raw-thread blocks.  ``full_data`` is never read as training data.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "1.0.0"
SPLITS = ("train", "dev", "test")
SOURCE = "mailex"
RAW_ALIGNMENT_THRESHOLD = 0.55
THREAD_SEPARATOR_RE = re.compile(r"(?m)^-{20,}\s*$")
HEADER_RE = re.compile(r"(?i)^(FROM|TO|CC|SUBJECT|DATE|SENT):\s*(.*)$")
WORD_RE = re.compile(r"[a-z0-9]+")

# A deliberately small, deterministic detokenization policy.  Tokens remain
# untouched in ``tokens``; these rules affect only the readable ``text`` view.
NO_SPACE_BEFORE = re.compile(
    r"^(?:[.,!?;:%)\]}]|n't|'(?:s|re|ve|ll|d|m)|’(?:s|re|ve|ll|d|m))$",
    re.I,
)
NO_SPACE_AFTER = re.compile(r"^(?:[(\[{]|[$#])$")

REQUIRED_RECORD_KEYS = {
    "id",
    "source",
    "source_split",
    "source_filename",
    "thread_id",
    "turn_index",
    "text",
    "tokens",
    "token_offsets",
    "sender",
    "recipients",
    "timestamp",
    "subject",
    "thread_context",
    "original_events",
    "text2task_annotations",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("data/raw/mailex"),
        help="MailEx root containing train/dev/test and optional raw_threads",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/unified"),
        help="Directory for train/dev/test JSONL files",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("data/reports/conversion_report.md"),
        help="Markdown conversion report",
    )
    parser.add_argument(
        "--raw-alignment-threshold",
        type=float,
        default=RAW_ALIGNMENT_THRESHOLD,
        help="Minimum normalized-text similarity for raw metadata alignment",
    )
    return parser.parse_args()


def token_surface(token: Any) -> str:
    """Return the deterministic text surface for one preserved token value.

    MailEx normally stores strings, but 328 audited turns contain nested empty
    list values.  Recursively joining list leaves preserves those values in the
    token array while still giving them a well-defined (empty) text surface.
    Other JSON scalar anomalies are rendered with their JSON representation so
    that conversion remains explicit and deterministic rather than lossy.
    """

    if isinstance(token, str):
        return token
    if isinstance(token, list):
        return " ".join(token_surface(item) for item in token)
    return json.dumps(token, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def needs_space(previous_surface: str, current_surface: str) -> bool:
    if not previous_surface or not current_surface:
        return False
    if NO_SPACE_BEFORE.match(current_surface):
        return False
    if NO_SPACE_AFTER.match(previous_surface):
        return False
    return True


def reconstruct_text(tokens: list[Any]) -> tuple[str, list[list[int]]]:
    """Detokenize while producing [start, end] offsets for every token index."""

    pieces: list[str] = []
    offsets: list[list[int]] = []
    cursor = 0
    previous_surface = ""
    for token in tokens:
        surface = token_surface(token)
        if pieces and needs_space(previous_surface, surface):
            pieces.append(" ")
            cursor += 1
        start = cursor
        pieces.append(surface)
        cursor += len(surface)
        offsets.append([start, cursor])
        previous_surface = surface
    return "".join(pieces), offsets


def normalized_text(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def record_id(source_split: str, thread_id: str, turn_index: int) -> str:
    """Return a readable ID whose inputs fully determine its value."""

    return f"mailex:{source_split}:{thread_id}:turn_{turn_index:04d}"


def raw_key(path: Path) -> str:
    return path.name[:-1] if path.name.endswith(".") else path.name


def parse_raw_blocks(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = [chunk for chunk in THREAD_SEPARATOR_RE.split(text) if chunk.strip()]
    blocks: list[dict[str, Any]] = []
    for block_index, chunk in enumerate(chunks):
        lines = chunk.strip().splitlines()
        headers: dict[str, str] = {}
        body_start = 0
        saw_header = False
        for line_index, line in enumerate(lines[:10]):
            match = HEADER_RE.match(line)
            if match:
                saw_header = True
                headers[match.group(1).upper()] = match.group(2).strip()
                body_start = line_index + 1
            elif saw_header or line.strip():
                break
        blocks.append(
            {
                "raw_block_index": block_index,
                "headers": headers,
                "body": "\n".join(lines[body_start:]).strip(),
            }
        )
    return blocks


def similarity(left: str, right: str) -> float:
    left_norm = normalized_text(left)
    right_norm = normalized_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    return difflib.SequenceMatcher(None, left_norm, right_norm).ratio()


def align_raw_blocks(
    turn_texts: list[str], raw_blocks: list[dict[str, Any]], threshold: float
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    """Greedily choose a one-to-one maximum-similarity turn/block alignment.

    MailEx raw blocks are normally reverse chronological and occasionally have
    extra/missing delimiter chunks.  Comparing all pairs avoids assuming either
    positional order.  A threshold prevents unrelated headers from becoming
    invented metadata.
    """

    candidates: list[tuple[float, int, int]] = []
    for turn_index, turn_text in enumerate(turn_texts):
        for raw_index, block in enumerate(raw_blocks):
            candidates.append((similarity(turn_text, block["body"]), turn_index, raw_index))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_turns: set[int] = set()
    used_blocks: set[int] = set()
    aligned: dict[int, dict[str, Any]] = {}
    rejected_best: list[dict[str, Any]] = []
    best_per_turn: dict[int, tuple[float, int]] = {}
    for score, turn_index, raw_index in candidates:
        best_per_turn.setdefault(turn_index, (score, raw_index))
        if score < threshold or turn_index in used_turns or raw_index in used_blocks:
            continue
        used_turns.add(turn_index)
        used_blocks.add(raw_index)
        aligned[turn_index] = {
            **raw_blocks[raw_index],
            "alignment_score": round(score, 6),
        }
    for turn_index in range(len(turn_texts)):
        if turn_index not in aligned:
            score, raw_index = best_per_turn.get(turn_index, (0.0, -1))
            rejected_best.append(
                {
                    "turn_index": turn_index,
                    "best_raw_block_index": raw_index,
                    "best_score": round(score, 6),
                }
            )
    return aligned, rejected_best


def parse_recipients(value: str | None) -> list[str]:
    if not value:
        return []
    # Semicolons are reliable separators in display-name headers containing
    # commas ("Bass, Eric; ...").  Otherwise the source commonly uses commas.
    separator = ";" if ";" in value else ","
    return [part.strip() for part in value.split(separator) if part.strip()]


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_RECORD_KEYS - set(record)
    if missing:
        errors.append(f"missing keys: {sorted(missing)}")
    if record.get("source") != SOURCE:
        errors.append("source is not 'mailex'")
    if record.get("source_split") not in SPLITS:
        errors.append("invalid source_split")
    if not isinstance(record.get("tokens"), list):
        errors.append("tokens is not a list")
        return errors
    if not isinstance(record.get("token_offsets"), list):
        errors.append("token_offsets is not a list")
        return errors
    if len(record["tokens"]) != len(record["token_offsets"]):
        errors.append("token/offset length mismatch")
    text = record.get("text")
    if not isinstance(text, str):
        errors.append("text is not a string")
        return errors
    previous_start = 0
    for index, (token, offset) in enumerate(zip(record["tokens"], record["token_offsets"])):
        if (
            not isinstance(offset, list)
            or len(offset) != 2
            or not all(isinstance(value, int) for value in offset)
        ):
            errors.append(f"offset {index} is not [int, int]")
            continue
        start, end = offset
        if not (0 <= start <= end <= len(text)):
            errors.append(f"offset {index} is outside text")
            continue
        if start < previous_start:
            errors.append(f"offset {index} is not monotonic")
        if text[start:end] != token_surface(token):
            errors.append(f"offset {index} does not reconstruct token surface")
        previous_start = start
    if record.get("sender") is not None and not isinstance(record.get("sender"), str):
        errors.append("sender is neither string nor null")
    if not isinstance(record.get("recipients"), list) or not all(
        isinstance(value, str) for value in record.get("recipients", [])
    ):
        errors.append("recipients is not a list of strings")
    if record.get("timestamp") is not None and not isinstance(record.get("timestamp"), str):
        errors.append("timestamp is neither string nor null")
    if not isinstance(record.get("original_events"), dict):
        errors.append("original_events is not an object")
    if record.get("text2task_annotations") is not None:
        errors.append("text2task_annotations is not null")
    try:
        json.dumps(record, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        errors.append(f"not JSON-serializable: {error}")
    return errors


def build_raw_lookup(raw_dir: Path) -> tuple[dict[str, Path], dict[str, list[str]]]:
    if not raw_dir.is_dir():
        return {}, {}
    grouped: defaultdict[str, list[Path]] = defaultdict(list)
    for path in sorted(raw_dir.iterdir()):
        if path.is_file() and not path.name.startswith("."):
            grouped[raw_key(path)].append(path)
    lookup = {key: paths[0] for key, paths in grouped.items()}
    collisions = {key: [path.name for path in paths] for key, paths in grouped.items() if len(paths) > 1}
    return lookup, collisions


def convert_split(
    split: str,
    dataset_root: Path,
    raw_lookup: dict[str, Path],
    raw_threshold: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    split_dir = dataset_root / split
    if not split_dir.is_dir():
        raise ValueError(f"Missing split directory: {split_dir}")
    source_files = sorted(split_dir.glob("*.json"))
    records: list[dict[str, Any]] = []
    stats: Counter[str] = Counter()
    warnings: list[dict[str, Any]] = []

    for source_path in source_files:
        data = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("sentences"), list) or not isinstance(data.get("events"), dict):
            raise ValueError(f"Unsupported MailEx structure in {source_path}")
        thread_id = source_path.stem
        sentences = data["sentences"]
        events = data["events"]
        turn_text_and_offsets = []
        for turn_index, tokens in enumerate(sentences):
            if not isinstance(tokens, list):
                raise ValueError(f"Turn is not a token list: {source_path} turn_{turn_index}")
            turn_text_and_offsets.append(reconstruct_text(tokens))

        raw_path = raw_lookup.get(thread_id)
        raw_blocks = parse_raw_blocks(raw_path) if raw_path else []
        aligned, rejected = align_raw_blocks(
            [text for text, _ in turn_text_and_offsets], raw_blocks, raw_threshold
        )
        if raw_path:
            stats["threads_with_raw_file"] += 1
            stats["raw_blocks"] += len(raw_blocks)
        else:
            stats["threads_without_raw_file"] += 1
        stats["raw_aligned_turns"] += len(aligned)
        stats["raw_unaligned_turns"] += len(sentences) - len(aligned)
        if rejected:
            warnings.append(
                {
                    "source_filename": source_path.name,
                    "issue": "turns_without_confident_raw_alignment",
                    "details": rejected,
                }
            )
        if raw_path and len(raw_blocks) != len(sentences):
            warnings.append(
                {
                    "source_filename": source_path.name,
                    "issue": "raw_block_count_differs_from_annotated_turn_count",
                    "annotated_turns": len(sentences),
                    "raw_blocks": len(raw_blocks),
                }
            )

        stats["threads"] += 1
        stats["turns"] += len(sentences)
        for turn_index, tokens in enumerate(sentences):
            turn_key = f"turn_{turn_index}"
            if turn_key not in events:
                raise ValueError(f"Missing {turn_key} events in {source_path}")
            text, offsets = turn_text_and_offsets[turn_index]
            rid = record_id(split, thread_id, turn_index)
            raw_match = aligned.get(turn_index)
            headers = raw_match["headers"] if raw_match else {}
            sender = headers.get("FROM") or None
            recipients = parse_recipients(headers.get("TO"))
            timestamp = headers.get("SENT") or headers.get("DATE") or None
            subject = headers.get("SUBJECT") or None
            if sender:
                stats["sender_present"] += 1
            if recipients:
                stats["recipients_present"] += 1
            if timestamp:
                stats["timestamp_present"] += 1
            if subject:
                stats["subject_present"] += 1
            non_string_indices = [index for index, token in enumerate(tokens) if not isinstance(token, str)]
            if non_string_indices:
                stats["turns_with_non_string_tokens"] += 1
                warnings.append(
                    {
                        "source_filename": source_path.name,
                        "turn_index": turn_index,
                        "issue": "preserved_non_string_tokens",
                        "token_indices": non_string_indices,
                    }
                )

            previous_id = record_id(split, thread_id, turn_index - 1) if turn_index > 0 else None
            next_id = record_id(split, thread_id, turn_index + 1) if turn_index + 1 < len(sentences) else None
            record = {
                "id": rid,
                "source": SOURCE,
                "source_split": split,
                "source_filename": source_path.name,
                "thread_id": thread_id,
                "turn_index": turn_index,
                "text": text,
                "tokens": tokens,
                "token_offsets": offsets,
                "sender": sender,
                "recipients": recipients,
                "timestamp": timestamp,
                "subject": subject,
                "thread_context": {
                    "turn_count": len(sentences),
                    "previous_record_id": previous_id,
                    "next_record_id": next_id,
                    "raw_thread_filename": raw_path.name if raw_path else None,
                    "raw_block_index": raw_match["raw_block_index"] if raw_match else None,
                    "raw_alignment_score": raw_match["alignment_score"] if raw_match else None,
                },
                "original_events": events[turn_key],
                "text2task_annotations": None,
            }
            validation_errors = validate_record(record)
            if validation_errors:
                raise ValueError(f"Invalid converted record {rid}: {validation_errors}")
            records.append(record)
            stats["tokens"] += len(tokens)

    return records, {
        "source_files": len(source_files),
        **{key: stats[key] for key in sorted(stats)},
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=False))
            handle.write("\n")
            count += 1
    return count


def truncate(text: str, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    def clean(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(map(clean, headers)) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    lines.extend("| " + " | ".join(map(clean, row)) + " |" for row in rows)
    return "\n".join(lines)


def make_report(
    dataset_root: Path,
    output_dir: Path,
    stats_by_split: dict[str, dict[str, Any]],
    hashes: dict[str, str],
    inspection_records: list[dict[str, Any]],
    raw_threshold: float,
    raw_collisions: dict[str, list[str]],
) -> str:
    split_rows = []
    for split in SPLITS:
        stats = stats_by_split[split]
        split_rows.append(
            [
                split,
                stats["source_files"],
                stats["turns"],
                stats["tokens"],
                stats.get("raw_aligned_turns", 0),
                stats.get("sender_present", 0),
                stats.get("recipients_present", 0),
                stats.get("timestamp_present", 0),
                stats.get("turns_with_non_string_tokens", 0),
            ]
        )
    totals = Counter()
    for stats in stats_by_split.values():
        for key, value in stats.items():
            if isinstance(value, int):
                totals[key] += value
    split_rows.append(
        [
            "Total",
            totals["source_files"],
            totals["turns"],
            totals["tokens"],
            totals["raw_aligned_turns"],
            totals["sender_present"],
            totals["recipients_present"],
            totals["timestamp_present"],
            totals["turns_with_non_string_tokens"],
        ]
    )
    inspection_rows = [
        [
            record["id"],
            record["source_filename"],
            record["turn_index"],
            len(record["tokens"]),
            "yes" if record["sender"] else "no",
            truncate(record["text"]),
        ]
        for record in inspection_records
    ]
    warning_rows = [
        [split, stats["warning_count"], stats.get("raw_unaligned_turns", 0), stats.get("threads_without_raw_file", 0)]
        for split, stats in stats_by_split.items()
    ]

    return f"""# MailEx Unified Conversion Report

## Result

The authoritative MailEx `train`, `dev`, and `test` directories were converted to one JSONL record per annotated email turn. `full_data` was not read or counted as independent data. All **{totals['turns']:,}** turns were retained, including the audited non-string-token anomalies.

{markdown_table(['Split', 'Thread files', 'Turn records', 'Tokens', 'Raw metadata aligned', 'Sender present', 'Recipients present', 'Timestamp present', 'Non-string token turns'], split_rows)}

## Representation and preservation

- `tokens` is copied verbatim from the source `sentences[turn_index]`; token order and indices are unchanged.
- `original_events` is copied verbatim from `events["turn_i"]`, preserving triggers, BIO sequences, extras, and all original token-index references.
- `text` is a deterministic readable view using a small punctuation/contraction detokenization policy. It is not a cleaned or boilerplate-stripped representation.
- `token_offsets[i]` is `[start, end]` into `text`, and every `text[start:end]` was verified against the deterministic surface of `tokens[i]`.
- Nested token anomalies are retained. A nested empty-list token has an empty surface and therefore a zero-width offset; it is never discarded.
- `thread_id`, `turn_index`, `thread_context.previous_record_id`, and `thread_context.next_record_id` preserve email boundaries and ordering.
- IDs use `mailex:<split>:<source filename stem>:turn_<zero-padded index>` and are deterministic and unique.
- Sender, recipients, timestamp, and subject are populated only from a raw block aligned at normalized-text similarity ≥ {raw_threshold:.2f}. Otherwise they are `null`/`[]`.

## Output integrity

All records passed structural, JSON-serialization, offset-boundary, monotonicity, and exact reconstruction checks before writing. Source split/file counts were preserved.

{markdown_table(['Output', 'SHA-256'], [[f'{split}.jsonl', hashes[split]] for split in SPLITS])}

The converter version is `{SCRIPT_VERSION}`. Dataset root: `{dataset_root}`. Output directory: `{output_dir}`.

## Raw metadata alignment and warnings

Raw files are usually reverse chronological and occasionally have extra or missing delimiter chunks. The converter compares all annotated turns with all raw blocks and accepts a deterministic one-to-one match only above the configured threshold; it does not guess metadata for rejected matches.

{markdown_table(['Split', 'Warnings', 'Unaligned turns', 'Threads without raw file'], warning_rows)}

Normalized raw filename collisions: **{len(raw_collisions)}**. Detailed per-file warnings are intentionally summarized here; conversion never drops a turn because raw metadata is missing or ambiguous.

## Manual inspection sample

The following {len(inspection_records)} records come from different threads and were selected deterministically across all three splits after conversion:

{markdown_table(['Record ID', 'Source file', 'Turn', 'Tokens', 'Sender?', 'Text preview'], inspection_rows)}

## Reproduction

```bash
python3 scripts/convert_mailex.py
python3 -m unittest tests/test_convert_mailex.py
```
"""


def select_inspection_records(records_by_split: dict[str, list[dict[str, Any]]], count: int = 12) -> list[dict[str, Any]]:
    """Select records deterministically, covering every split and unique threads."""

    selected: list[dict[str, Any]] = []
    seen_threads: set[tuple[str, str]] = set()
    per_split_target = {"train": 4, "dev": 4, "test": 4}
    for split in SPLITS:
        for record in records_by_split[split]:
            key = (split, record["thread_id"])
            if key in seen_threads:
                continue
            selected.append(record)
            seen_threads.add(key)
            if sum(item["source_split"] == split for item in selected) >= per_split_target[split]:
                break
    if len(selected) < count:
        for split in SPLITS:
            for record in records_by_split[split]:
                key = (split, record["thread_id"])
                if key not in seen_threads:
                    selected.append(record)
                    seen_threads.add(key)
                    if len(selected) >= count:
                        break
            if len(selected) >= count:
                break
    return selected[:count]


def convert(
    dataset_root: Path,
    output_dir: Path,
    report_path: Path,
    raw_threshold: float = RAW_ALIGNMENT_THRESHOLD,
) -> dict[str, Any]:
    dataset_root = dataset_root.resolve()
    output_dir = output_dir.resolve()
    report_path = report_path.resolve()
    if not 0.0 <= raw_threshold <= 1.0:
        raise ValueError("raw alignment threshold must be between 0 and 1")

    raw_lookup, raw_collisions = build_raw_lookup(dataset_root / "raw_threads")
    records_by_split: dict[str, list[dict[str, Any]]] = {}
    stats_by_split: dict[str, dict[str, Any]] = {}
    all_ids: set[str] = set()

    for split in SPLITS:
        records, stats = convert_split(split, dataset_root, raw_lookup, raw_threshold)
        source_file_count = len(list((dataset_root / split).glob("*.json")))
        if stats["source_files"] != source_file_count:
            raise ValueError(f"Source file count changed during conversion for {split}")
        duplicate_ids = [record["id"] for record in records if record["id"] in all_ids]
        if duplicate_ids:
            raise ValueError(f"Duplicate record IDs: {duplicate_ids[:5]}")
        all_ids.update(record["id"] for record in records)
        records_by_split[split] = records
        stats_by_split[split] = stats

    hashes: dict[str, str] = {}
    for split in SPLITS:
        output_path = output_dir / f"{split}.jsonl"
        written = write_jsonl(records_by_split[split], output_path)
        if written != stats_by_split[split]["turns"]:
            raise ValueError(f"Output count mismatch for {split}: {written}")
        hashes[split] = sha256_path(output_path)

    inspection_records = select_inspection_records(records_by_split)
    if len(inspection_records) < 10 or len({record["thread_id"] for record in inspection_records}) < 10:
        raise ValueError("Could not select at least 10 records from different threads")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        make_report(
            dataset_root,
            output_dir,
            stats_by_split,
            hashes,
            inspection_records,
            raw_threshold,
            raw_collisions,
        ),
        encoding="utf-8",
    )
    return {
        "stats_by_split": stats_by_split,
        "hashes": hashes,
        "inspection_record_ids": [record["id"] for record in inspection_records],
        "total_records": sum(len(records) for records in records_by_split.values()),
    }


def main() -> None:
    args = parse_args()
    result = convert(args.dataset_root, args.output_dir, args.report_path, args.raw_alignment_threshold)
    print("MailEx conversion complete")
    for split in SPLITS:
        stats = result["stats_by_split"][split]
        print(
            f"  {split}: {stats['source_files']:,} threads -> {stats['turns']:,} records; "
            f"{stats.get('raw_aligned_turns', 0):,} with aligned raw metadata"
        )
    print(f"  Total records: {result['total_records']:,}")
    print(f"  Inspected sample: {len(result['inspection_record_ids'])} records from different threads")
    print(f"  Output directory: {args.output_dir.resolve()}")
    print(f"  Report: {args.report_path.resolve()}")


if __name__ == "__main__":
    main()
