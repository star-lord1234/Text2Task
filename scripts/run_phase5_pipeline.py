#!/usr/bin/env python3
"""Replay a conversation through Phase 5 and print proposals + final task states.

--scenario FILE [--name PREFIX]   scripted fixtures (extractor output is SCRIPTED; clearly labelled)
--messages FILE                   LIVE: messages [{id,sender,recipients,ts,tz,thread,text}] run through the real entity
                                  checkpoint -> Phase 3 relation model -> Phase 4 -> Phase 5. Proposals stay pending
                                  unless --auto-accept-creates (a simulated reviewer for demos; labelled in the output).
Review mode only. Nothing is applied without an explicit accept.
"""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))

from src.pipeline.contracts import MessageEnvelope, Participant  # noqa: E402
from src.pipeline.identity_resolution import ParticipantRegistry  # noqa: E402
from src.pipeline.task_fields import build_task_candidates  # noqa: E402
from src.reconciliation.reconciler import Reconciler  # noqa: E402
from src.reconciliation.scenario_runner import run_scenario  # noqa: E402
from src.reconciliation.store import TaskStore  # noqa: E402


def show_state(store, ws):
    return {t.task_id: {"title": t.title, "owner": t.owner_id, "status": t.status, "version": t.version,
                        "due": (t.due or {}).get("value") or (t.due or {}).get("raw"),
                        "scheduled": (t.scheduled or {}).get("value") or (t.scheduled or {}).get("raw"),
                        "pending": {k: (v["value"] or {}).get("value") for k, v in t.pending_changes.items()}} for t in store.list_tasks(ws)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", type=Path)
    ap.add_argument("--name", default="")
    ap.add_argument("--messages", type=Path)
    ap.add_argument("--registry", type=Path)
    ap.add_argument("--db", default=":memory:")
    ap.add_argument("--auto-accept-creates", action="store_true")
    ap.add_argument("--workspace", default="w")
    a = ap.parse_args()

    if a.scenario:
        out = []
        for sc in json.loads(a.scenario.read_text())["scenarios"]:
            if sc["name"].startswith(a.name):
                r = run_scenario(sc)
                out.append({"scenario": sc["name"], "mode": "SCRIPTED (extractor output is scripted)", "passed": r["passed"],
                            "failures": r["failures"], "trace": r["trace"], "final_tasks": r["tasks"]})
        print(json.dumps(out, indent=2, default=str))
        return

    if not a.messages or not a.registry:
        raise SystemExit("live mode needs --messages and --registry")
    from src.model_training.entity_inference import predict_entities
    from src.model_training.relation_classifier import RelationPredictor, detect_device
    registry = ParticipantRegistry.from_json(a.registry)
    store = TaskStore(a.db)
    rec = Reconciler(store)
    predictor = RelationPredictor(ROOT / "models/text2task-relations/ACTIVE")
    entity_model = ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted"
    log = []
    for m in json.loads(a.messages.read_text()):
        env = MessageEnvelope(m["id"], m["text"], m.get("sender"), m.get("recipients", []), m.get("ts"), m.get("tz"),
                              m.get("thread", "th1"), m.get("reply_to"))
        ents = predict_entities([m["text"]], entity_model, detect_device())[0]
        rels = predictor.predict(m["text"], ents)["relations"]
        cands = build_task_candidates(env, ents, rels, registry, primary_source="neural", config=rec.phase4_config)
        res = rec.process_message(env, ents, cands, registry, workspace_id=a.workspace, source_kind="neural")
        if a.auto_accept_creates:
            for p in res.proposals:
                if p.operation == "CREATE_TASK":
                    rec.accept(a.workspace, p.proposal_id, "simulated-reviewer")
        log.append({"message": m["id"], "mode": "LIVE (real models)", "entities": ents,
                    "proposals": [{"id": p.proposal_id, "operation": p.operation, "task_id": p.task_id, "field": p.field, "after": p.after,
                                   "status": p.status, "flags": [f["code"] for f in p.flags], "note": p.note} for p in res.proposals + res.no_actions]})
    print(json.dumps({"log": log, "tasks": show_state(store, a.workspace),
                      "note": "proposals other than simulated creates are still pending review"}, indent=2, default=str))


if __name__ == "__main__":
    main()
