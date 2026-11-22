#!/usr/bin/env python3
"""Run entities -> relations -> Phase 4 task candidates for one message (provisional SILVER models).

Neural relations by default. --rules makes the rule linker the primary source (explicit opt-in, never a
silent fallback); --with-rule-comparator adds MODEL_DISAGREEMENT flags. No timestamp is invented:
without --timestamp, relative dates stay UNRESOLVED_NO_ANCHOR.
"""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.baselines.rule_relations import predict_rules  # noqa: E402
from src.pipeline.contracts import MessageEnvelope, Participant  # noqa: E402
from src.pipeline.identity_resolution import ParticipantRegistry  # noqa: E402
from src.pipeline.task_fields import build_task_candidates  # noqa: E402
from src.pipeline.uncertainty import load_config  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--text", required=True)
    ap.add_argument("--message-id", default="msg-1")
    ap.add_argument("--sender", help="sender participant id (must exist in --registry, or be a plain name)")
    ap.add_argument("--recipient", action="append", default=[], help="recipient participant id (repeatable)")
    ap.add_argument("--registry", type=Path, help='JSON {"participants":[{"id","display_name","aliases","emails"}]}')
    ap.add_argument("--timestamp", help="ISO-8601 message time; never defaulted")
    ap.add_argument("--timezone", help="IANA zone, e.g. America/Chicago")
    ap.add_argument("--entities", type=Path, help="JSON list of entities; otherwise predicted")
    ap.add_argument("--relations-model", type=Path, default=ROOT / "models/text2task-relations/ACTIVE")
    ap.add_argument("--entity-model", type=Path, default=ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted")
    ap.add_argument("--rules", action="store_true")
    ap.add_argument("--with-rule-comparator", action="store_true")
    ap.add_argument("--config", type=Path)
    a = ap.parse_args()

    cfg = load_config(a.config)
    if a.registry:
        registry = ParticipantRegistry.from_json(a.registry)
    else:  # ad-hoc: participants named on the command line (id == display name)
        names = [n for n in [a.sender, *a.recipient] if n]
        registry = ParticipantRegistry([Participant(n, n, [n.split()[0]], low_trust=True) for n in dict.fromkeys(names)])
    env = MessageEnvelope(a.message_id, a.text, a.sender, a.recipient, a.timestamp, a.timezone)

    if a.entities:
        entities = json.loads(a.entities.read_text())
    else:
        from src.model_training.entity_inference import predict_entities
        from src.model_training.relation_classifier import detect_device
        entities = predict_entities([a.text], a.entity_model, detect_device())[0]

    comparator = None
    if a.rules:
        primary, source = predict_rules(a.text, entities)["relations"], "rule"
    else:
        from src.model_training.relation_classifier import RelationPredictor
        primary, source = RelationPredictor(a.relations_model).predict(a.text, entities)["relations"], "neural"
        if a.with_rule_comparator:
            comparator = predict_rules(a.text, entities)["relations"]
    cands = build_task_candidates(env, entities, primary, registry, primary_source=source,
                                  comparator_relations=comparator, config=cfg)
    print(json.dumps({"entities": entities, "candidates": [c.to_dict() for c in cands]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
