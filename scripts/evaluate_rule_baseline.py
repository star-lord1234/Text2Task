#!/usr/bin/env python3
"""Score the rule-based baseline (E1) on the same model-ready rows used for the neural models."""
import argparse, json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.baselines.rule_based import extract_spans, spans_to_bio  # noqa: E402
from src.model_training.span_metrics import evaluate, format_table  # noqa: E402

TYPES = ["TASK", "PERSON", "TEMPORAL"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", type=Path, default=Path("data/model_ready/entities_mailex_v1"))
    p.add_argument("--split", choices=["train", "validation"], default="validation")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    rows = [json.loads(l) for l in (a.data_dir / f"{a.split}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    preds, refs, records = [], [], []
    for r in rows:
        active = [i for i, lab in enumerate(r["labels"]) if lab is not None]
        offsets = [r["offset_mapping"][i] for i in active]
        spans = extract_spans(r["text"])
        pred = spans_to_bio(offsets, spans)
        ref = [r["labels"][i] for i in active]
        preds.append(pred); refs.append(ref)
        records.append({"id": r["id"], "predictions": pred, "references": ref})
    result = evaluate(preds, refs, TYPES)
    result.update({"rows": len(rows), "split": a.split, "baseline": "rule_based_E1"})
    print(f"Rule-based baseline on {a.split} ({len(rows)} rows)\n")
    print(format_table(result))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


main()
