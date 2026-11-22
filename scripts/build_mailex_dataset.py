#!/usr/bin/env python3
"""Build single-layer TASK/PERSON/TEMPORAL model data from MailEx human annotations.

Reads data/unified/{train,dev}.jsonl. The MailEx test split is deliberately NOT read
here; it is built only in the final evaluation phase.
"""

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

from scripts.build_entity_dataset_v2 import LABELS, model_record, read_jsonl, resolve_single_layer, write_jsonl  # noqa: E402
from src.annotation.mailex_labels import build_entities, load_mapping  # noqa: E402
from src.model_data.token_classification import DistilBertWordPieceTokenizer, prepare_record  # noqa: E402

SPLIT_FILES = {"train": "train", "validation": "dev"}


def snap_to_wordpieces(text: str, entities: list[dict[str, Any]], pieces: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expand each span outward to WordPiece boundaries; return (entities, snap_log)."""
    out, log = [], []
    for entity in entities:
        s, e = int(entity["start"]), int(entity["end"])
        first = next((p for p in pieces if int(p["end"]) > s), None)
        last = next((p for p in reversed(pieces) if int(p["start"]) < e), None)
        if first is None or last is None:
            log.append({"reason": "no_wordpiece", "entity": entity})
            continue
        ns, ne = min(s, int(first["start"])), max(e, int(last["end"]))
        if (ns, ne) != (s, e):
            log.append({"reason": "snapped", "before": text[s:e], "after": text[ns:ne], "type": entity["type"]})
        updated = dict(entity)
        updated.update({"start": ns, "end": ne, "text": text[ns:ne]})
        out.append(updated)
    return out, log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unified-dir", type=Path, default=Path("data/unified"))
    parser.add_argument("--mapping", type=Path, default=Path("configs/mailex_to_text2task_v1.json"))
    parser.add_argument("--records-dir", type=Path, default=Path("data/mailex_v1/records"))
    parser.add_argument("--output-model", type=Path, default=Path("data/model_ready/entities_mailex_v1"))
    parser.add_argument("--vocab", type=Path, default=Path("configs/tokenizers/distilbert-base-uncased-vocab.txt"))
    parser.add_argument("--requests-only", action="store_true", help="exclude commitment TASKs (ablation)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mapping = load_mapping(args.mapping)
    tokenizer = DistilBertWordPieceTokenizer(args.vocab)
    statistics: dict[str, Any] = {"splits": {}}
    split_threads: dict[str, set[str]] = {}
    for split, source in SPLIT_FILES.items():
        rows = read_jsonl(args.unified_dir / f"{source}.jsonl")
        records, model_rows, stats, drops = [], [], Counter(), []
        type_counts: Counter = Counter()
        for row in rows:
            if not row["text"].strip():
                stats["empty_text_records_skipped"] += 1
                continue
            entities, dropped, row_stats = build_entities(row, mapping, include_commitments=not args.requests_only)
            stats.update(row_stats)
            drops.extend({"record": row["id"], **d} for d in dropped)
            pieces = tokenizer.tokenize_with_offsets(row["text"])
            entities, snap_log = snap_to_wordpieces(row["text"], entities, pieces)
            for item in snap_log:
                stats[f"wordpiece_{item['reason']}"] += 1
                drops.append({"record": row["id"], **item})
            kept, overlap_dropped = resolve_single_layer(entities)
            for item in overlap_dropped:
                stats[f"overlap_dropped_{item['entity']['type']}"] += 1
                drops.append({"record": row["id"], "reason": "single_layer_overlap", "type": item["entity"]["type"], "text": item["entity"]["text"]})
            provenance = {
                "quality_tier": "MAILEX_DERIVED", "human_verified": False, "human_source": "MailEx annotators",
                "mapping_version": mapping["version"], "include_commitments": not args.requests_only,
                "note": "Spans derived from MailEx human event annotations by a deterministic mapping; not independently reviewed against the Text2Task schema.",
            }
            record = model_record(row, kept, provenance)
            records.append(record)
            prepared, info = prepare_record(record, tokenizer, final_split=split, max_length=512, stride=64)
            if info["layers"] != 1:
                raise ValueError(f"{row['id']}: produced {info['layers']} layers")
            model_rows.extend(prepared)
            type_counts.update(e["type"] for e in kept)
        write_jsonl(args.records_dir / f"{split}.jsonl", records)
        write_jsonl(args.records_dir / f"{split}_drop_log.jsonl", drops)
        write_jsonl(args.output_model / f"{split}.jsonl", model_rows)
        split_threads[split] = {r["thread_id"] for r in records}
        statistics["splits"][split] = {
            "source_records": len(records), "model_rows": len(model_rows),
            "threads": len(split_threads[split]), "entity_counts": dict(sorted(type_counts.items())),
            "records_with_no_entities": sum(1 for r in records if not r["text2task_annotations"]["entities"]),
            "multi_window_rows": sum(1 for r in model_rows if r["window_count"] > 1),
            "mapping_stats": dict(sorted(stats.items())),
        }
    overlap = sorted(split_threads["train"] & split_threads["validation"])
    if overlap:
        raise ValueError(f"cross-split thread overlap: {overlap[:10]}")
    statistics.update({
        "version": f"entities-mailex-v1{'-requests-only' if args.requests_only else ''}",
        "mapping_version": mapping["version"], "include_commitments": not args.requests_only,
        "entity_types": ["TASK", "PERSON", "TEMPORAL"], "bio_labels": LABELS, "single_layer": True,
        "train_validation_thread_overlap": [], "test_data_read_or_modified": False,
        "mapping_sha256": hashlib.sha256(args.mapping.read_bytes()).hexdigest(),
    })
    args.output_model.mkdir(parents=True, exist_ok=True)
    (args.output_model / "label_map.json").write_text(json.dumps({
        "labels": LABELS, "label_to_id": {label: i for i, label in enumerate(LABELS)},
        "id_to_label": {str(i): label for i, label in enumerate(LABELS)}, "ignore_index": -100,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_model / "statistics.json").write_text(json.dumps(statistics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(statistics, indent=2))


if __name__ == "__main__":
    main()
