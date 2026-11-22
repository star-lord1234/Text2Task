#!/usr/bin/env python3
"""Phase 3 Step 2: build three-class-compatible relation data.

Scope: TASK->PERSON (ASSIGNED_TO) and TASK->TEMPORAL (DUE_ON, SCHEDULED_ON), plus NONE.
Train is negative-sampled; validation/test are full type-valid candidate sets (no sampling).
DEPENDS_ON / GROUP / EVENT / TASK->TASK are out of neural scope and counted in the manifest.
"""
from __future__ import annotations

import argparse, hashlib, json, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.model_data.relation_classification import candidate_rows_for_record, sample_negatives  # noqa: E402
from src.model_data.token_classification import atomic_json, atomic_jsonl, read_jsonl  # noqa: E402

LABELS = ["NONE", "ASSIGNED_TO", "DUE_ON", "SCHEDULED_ON"]
LABEL_TO_ID = {l: i for i, l in enumerate(LABELS)}
IN_SCOPE = {("TASK", "PERSON"), ("TASK", "TEMPORAL")}
SPLITS = ("train", "validation", "test")


def norm(t): return re.sub(r"\W+", " ", t.lower()).strip()


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", type=Path, default=ROOT / "data/final")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "data/model_ready/relations_v2_three_class")
    ap.add_argument("--negative-ratio", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=20261102)
    args = ap.parse_args()

    train_texts = {norm(r["text"]) for r in read_jsonl(args.input_dir / "train.jsonl")}
    manifest = {"task": "relation_classification_v2_three_class", "labels": LABELS, "seed": args.seed,
                "negative_ratio_train": args.negative_ratio, "scope": sorted("->".join(p) for p in IN_SCOPE),
                "inputs": {s: sha(args.input_dir / f"{s}.jsonl") for s in SPLITS},
                "provenance": "SILVER (MailEx-derived), not human-reviewed", "splits": {}}
    for split in SPLITS:
        recs = read_jsonl(args.input_dir / f"{split}.jsonl")
        dup = 0
        if split != "train":
            kept = [r for r in recs if norm(r["text"]) not in train_texts]
            dup = len(recs) - len(kept); recs = kept
        rows, out_of_scope = [], Counter()
        for r in recs:
            cand, _, _ = candidate_rows_for_record(r, final_split=split)
            for row in cand:
                key = (row["source_entity"]["type"], row["target_entity"]["type"])
                if key in IN_SCOPE:
                    row = dict(row, label_id=LABEL_TO_ID[row["label"]],
                               candidate_relation_types=[l for l in row["candidate_relation_types"]])
                    rows.append(row)
                elif row["label"] != "NONE":
                    out_of_scope[f"{row['label']}:{key[0]}->{key[1]}"] += 1
        pos_total = sum(r["label"] != "NONE" for r in rows)
        if split == "train":
            sampled = sample_negatives(rows, ratio=args.negative_ratio, seed=args.seed)
            atomic_jsonl(args.output_dir / "train.jsonl", sampled)
            atomic_jsonl(args.output_dir / "train_full.jsonl", rows)
            out = sampled
        else:
            atomic_jsonl(args.output_dir / f"{split}.jsonl", rows)
            out = rows
        c = Counter(r["label"] for r in out)
        manifest["splits"][split] = {
            "records_used": len(recs), "records_dropped_text_duplicate_of_train": dup,
            "threads": len({r["thread_id"] for r in recs}), "all_in_scope_candidates": len(rows),
            "rows_written": len(out), "label_counts": dict(sorted(c.items())),
            "full_candidate_label_counts": dict(sorted(Counter(r["label"] for r in rows).items())),
            "positives_out_of_scope_dropped": dict(out_of_scope), "positives_in_scope": pos_total}
    atomic_json(args.output_dir / "label_map.json", {"labels": LABELS, "label_to_id": LABEL_TO_ID})
    atomic_json(args.output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
