#!/usr/bin/env python3
"""Predict relations for text. Entities come from --entities JSON, or from the three-class entity checkpoint.

Neural by default; --rules uses the rule comparator (explicit opt-in, never an automatic fallback).
Scores are uncalibrated softmax values.
"""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--entities", type=Path, help="JSON list of {id,type,start,end,text}; otherwise predicted")
    ap.add_argument("--model", type=Path, default=ROOT / "models/text2task-relations/ACTIVE")
    ap.add_argument("--entity-model", type=Path, default=ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted")
    ap.add_argument("--rules", action="store_true")
    a = ap.parse_args()
    if a.entities:
        entities = json.loads(a.entities.read_text())
    else:
        sys.path.insert(0, str(ROOT / "scripts"))
        from src.model_training.entity_inference import predict_entities
        from src.model_training.relation_classifier import detect_device
        entities = predict_entities([a.text], a.entity_model, detect_device())[0]
    if a.rules:
        from src.baselines.rule_relations import predict_rules
        result = predict_rules(a.text, entities)
    else:
        from src.model_training.relation_classifier import RelationPredictor
        result = RelationPredictor(a.model).predict(a.text, entities)
    print(json.dumps({"entities": entities, **result}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
