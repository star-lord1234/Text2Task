#!/usr/bin/env python3
"""Build offset-verified DistilBERT BIO data from finalized Text2Task JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_data.reporting import write_model_data_report  # noqa: E402
from src.model_data.token_classification import prepare_all_splits  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/final"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/model_ready/entities"))
    parser.add_argument("--relations-dir", type=Path, default=Path("data/model_ready/relations"))
    parser.add_argument("--vocab", type=Path, default=Path("configs/tokenizers/distilbert-base-uncased-vocab.txt"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/model_data_statistics.md"))
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--stride", type=int, default=64)
    parser.add_argument("--samples", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.vocab.is_file():
        raise SystemExit(f"Missing official DistilBERT vocabulary: {args.vocab}")
    for split in ("train", "validation", "test"):
        if not (args.input_dir / f"{split}.jsonl").is_file():
            raise SystemExit(f"Missing finalized split: {args.input_dir / f'{split}.jsonl'}")
    stats = prepare_all_splits(
        args.input_dir,
        args.output_dir,
        args.vocab,
        max_length=args.max_length,
        stride=args.stride,
    )
    write_model_data_report(args.report, args.output_dir, args.relations_dir)
    print("DistilBERT token-classification data")
    for split, values in stats["splits"].items():
        print(
            f"  {split}: {values['source_records']} emails -> {values['model_rows']} rows; "
            f"{values['entities']} spans; {values['records_requiring_overlap_layers']} emails layered"
        )
    print("\nSample training records")
    with (args.output_dir / "train.jsonl").open(encoding="utf-8") as handle:
        for _ in range(max(0, args.samples)):
            line = handle.readline()
            if not line:
                break
            row = json.loads(line)
            labeled = [
                {"token": token, "offset": offset, "label": label, "entity_id": entity_id}
                for token, offset, label, entity_id in zip(row["tokens"], row["offset_mapping"], row["labels"], row["entity_ids"])
                if label not in {None, "O"}
            ]
            print(json.dumps({
                "id": row["id"],
                "source_record_id": row["source_record_id"],
                "thread_id": row["thread_id"],
                "layer": row["layer_index"],
                "window": row["window_index"],
                "labeled_wordpieces": labeled[:24],
                "entities": row["entities"],
            }, ensure_ascii=False, indent=2))
    print(f"Output: {args.output_dir.resolve()}")
    print(f"Report: {args.report.resolve()}")


if __name__ == "__main__":
    main()

