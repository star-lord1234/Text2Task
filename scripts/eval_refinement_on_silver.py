"""Phase 7.5: does refinement help or hurt on real EMAIL text? Entity-level agreement with provisional SILVER labels on the validation split
(read-only; the test split is never read; nothing here is used to tune a rule). Lenient match = same type and IoU >= 0.5.
Usage: .venv/bin/python scripts/eval_refinement_on_silver.py"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.model_training.entity_inference import EntityPredictor  # noqa: E402
from src.refine.config import from_preset  # noqa: E402
from src.refine.pipeline import refine  # noqa: E402

MODEL = ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted"
VAL = ROOT / "data/model_ready/entities_v2_three_class/validation.jsonl"


def iou(a, b):
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = (a["end"] - a["start"]) + (b["end"] - b["start"]) - inter
    return inter / union if union else 0.0


def score(pred, gold):
    out = {}
    for typ in ("TASK", "PERSON", "TEMPORAL", "ALL"):
        P = [p for p in pred if typ == "ALL" or p["type"] == typ]
        G = [g for g in gold if typ == "ALL" or g["type"] == typ]
        used, tp = set(), 0
        for p in P:
            best = max(((iou(p, g), i) for i, g in enumerate(G) if i not in used and g["type"] == p["type"]), default=(0, None))
            if best[0] >= 0.5:
                used.add(best[1]); tp += 1
        pr, rc = tp / len(P) if P else 0, tp / len(G) if G else 0
        out[typ] = {"predicted": len(P), "gold": len(G), "matched": tp, "precision": round(pr, 3), "recall": round(rc, 3), "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0}
    return out


def main() -> None:
    rows, seen = [], set()
    for line in VAL.read_text().splitlines():
        r = json.loads(line)
        if r["source_record_id"] not in seen:
            seen.add(r["source_record_id"]); rows.append(r)
    pred = EntityPredictor(MODEL)
    res = {}
    for preset in ("neural_only", "refined", "hybrid"):
        cfg = from_preset(preset)
        P, G, new = [], [], Counter()
        for r in rows:
            raw = pred.predict(r["text"])
            es = refine(r["text"], raw, cfg, []).entities
            off = 10_000_000 * len(G)                          # keep spans of different emails apart
            P += [{**e, "start": e["start"] + off, "end": e["end"] + off} for e in es]
            G += [{"type": e["type"], "start": e["start"] + off, "end": e["end"] + off} for e in r["entities"]]
            for e in es:
                new[e.get("origin", "neural")] += 1
        res[preset] = {"scores": score(P, G), "span_origins": dict(new)}
    out = {"scope": "SILVER validation, 60 emails, read-only; provisional labels, not human-verified. Lenient = same type, IoU >= 0.5.", "emails": len(rows), "results": res}
    (ROOT / "results/phase7_5/silver_validation.json").write_text(json.dumps(out, indent=1))
    for preset, v in res.items():
        print(preset, {t: (v["scores"][t]["precision"], v["scores"][t]["recall"], v["scores"][t]["f1"]) for t in ("TASK", "PERSON", "TEMPORAL", "ALL")}, v["span_origins"])


if __name__ == "__main__":
    main()
