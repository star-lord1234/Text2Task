"""Message processing (Phase 7).

Extraction is the ONLY place where the three sources differ:
  scripted : spans/links come from a scenario fixture (labelled 'scripted')
  live     : real checkpoints ('neural'); explicit prerequisite wording is added by the rule linker and labelled 'rule'
  fallback : opt-in rule baseline, only when the matching neural model is unavailable (labelled 'rule', surfaced in the banner)
Everything after extraction (Phase 4 fields, Phase 5 reconciliation, Phase 6 graph) is the same real code in every mode.
If extraction fails the message is kept with the error. Scripted output is NEVER substituted for a failed live run.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

from src.api.config import WORKSPACE
from src.api.services.model_registry import ModelRegistry, ModelUnavailable
from src.baselines.rule_based import extract_spans
from src.baselines.rule_relations import predict_rules
from src.pipeline.contracts import MessageEnvelope, Participant
from src.pipeline.identity_resolution import ParticipantRegistry
from src.pipeline.task_fields import build_task_candidates
from src.reconciliation.scenario_runner import build_entities
from src.refine.config import resolve as resolve_refine
from src.refine.pipeline import MODEL_VERSION, refine
from src.refine.relations import refine_relations

SCOPE = {"TASK", "PERSON", "TEMPORAL"}


def participant_registry(participants: list[dict[str, Any]]) -> ParticipantRegistry:
    return ParticipantRegistry([Participant(id=p["id"], display_name=p["name"], aliases=[p["name"].split()[0]]) for p in participants])


class PipelineService:
    def __init__(self, runtime: Any):
        self.rt = runtime

    # ------------------------------------------------------------------ extraction
    def _extract_scripted(self, text: str, scripted: dict[str, Any]):
        entities, ids = build_entities(text, scripted.get("spans", {}))
        relations = [{"source_id": ids[a], "target_id": ids[b], "label": lab, "score": None, "provenance": "scripted", "model_version": "scenario fixture"}
                     for a, b, lab in scripted.get("links", [])]
        return entities, relations, [], {"entities": "scripted", "relations": "scripted"}, {}, None, {}

    def _extract_live(self, text: str):
        """Live extraction. Returns (entities, relations, no_link, provenance, versions, refinement_record, reconciler_options).

        raw neural output -> (optional, individually switchable) refinement -> relation model on the REFINED entities -> rule dependency relations.
        The raw entities and the relations the model gives on them are kept next to the refined ones."""
        reg: ModelRegistry = self.rt.registry
        s = self.rt.app.settings()
        fallback = bool(s.get("allow_rule_fallback"))
        cfg = resolve_refine(s)
        participants = self.rt.app.participants()
        prov, versions = {}, {}
        # ---- raw entities
        if cfg.entity_source == "rule":
            raw = [{"id": f"rule-e{i}", "type": typ, "start": a, "end": b, "text": text[a:b], "confidence": None}
                   for i, (typ, a, b) in enumerate(extract_spans(text), 1) if typ in SCOPE]
            prov["entities"], versions["entities"] = "rule", "rule baseline (selected pipeline: rule_only)"
        else:
            try:
                raw = [e for e in reg.entity().predict(text) if e["type"] in SCOPE]
                prov["entities"], versions["entities"] = "neural", reg.info["entity"]["name"]
            except ModelUnavailable:
                if not fallback:
                    raise
                raw = [{"id": f"rule-e{i}", "type": typ, "start": a, "end": b, "text": text[a:b], "confidence": None}
                       for i, (typ, a, b) in enumerate(extract_spans(text), 1) if typ in SCOPE]
                prov["entities"], versions["entities"] = "rule", "rule baseline (opt-in fallback)"
        rule_entities = prov["entities"] == "rule"
        # ---- refinement (steps 2-5); the raw output is preserved untouched
        ref = refine(text, raw, cfg, participants)
        entities = ref.entities
        if ref.entities != raw and cfg.any_refinement:
            prov["entity_refinement"] = "rule"
        # ---- relations on the refined entities (raw-entity relations kept for comparison)
        no_link: list[dict[str, Any]] = []
        raw_relations: Optional[list[dict[str, Any]]] = None
        if rule_entities:
            relations = [r for r in predict_rules(text, entities)["relations"] if r["label"] != "DEPENDS_ON"]
            prov["relations"], versions["relations"] = "rule", "rule linker"
        else:
            try:
                out = reg.relation().predict(text, entities)
                relations, no_link = list(out["relations"]), list(out["no_link"]) + list(out["unrepresentable"])
                prov["relations"], versions["relations"] = "neural", reg.relation().version
                if cfg.any_refinement and entities != ref.raw_entities:
                    raw_relations = list(reg.relation().predict(text, [{k: v for k, v in e.items() if k in ("id", "type", "start", "end", "text", "confidence")}
                                                                       for e in ref.raw_entities])["relations"])
            except ModelUnavailable:
                if not fallback:
                    raise
                relations = [r for r in predict_rules(text, entities)["relations"] if r["label"] != "DEPENDS_ON"]
                prov["relations"], versions["relations"] = "rule", "rule linker (opt-in fallback)"
        relation_edits: list[dict[str, Any]] = []
        if cfg.grammar_recovery and not rule_entities:
            relations, relation_edits = refine_relations(text, entities, relations)
            if relation_edits:
                prov["relation_refinement"] = "rule"
        if cfg.rule_dependency_linker and s.get("rule_dependency_linker", True):
            dep = [dict(r, rule="explicit_prerequisite_cue") for r in predict_rules(text, entities)["relations"] if r["label"] == "DEPENDS_ON"]
            relations += dep
            if dep:
                prov["dependency_links"] = "rule"
        if ref.relations:
            have = {(r["source_id"], r["target_id"]) for r in relations if r["label"] == "DEPENDS_ON"}
            new = [r for r in ref.relations if (r["source_id"], r["target_id"]) not in have]
            relations += new
            if new:
                prov["dependency_links"] = "rule"
        record = ref.to_dict()
        record["raw_relations"] = raw_relations
        record["relation_edits"] = relation_edits
        record["version"] = MODEL_VERSION
        options = {"context_lifecycle": cfg.context_lifecycle, "clause_hints": ref.hints, "imperative_ids": ref.imperative_ids}
        return entities, relations, no_link, prov, versions, record, options

    # ------------------------------------------------------------------ main entry
    def process(self, message: dict[str, Any], *, scripted: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Analyse a persisted message. Returns the analysis record (also persisted). Never fabricates output."""
        app, rt = self.rt.app, self.rt
        mid, mode = message["id"], message["mode"]
        # deterministic: the same message analysed in the same mode for the n-th time always gets the same run id (exact replays)
        attempt = self.rt.store.conn.execute("SELECT COUNT(*) AS n FROM analyses WHERE message_id=?", (mid,)).fetchone()["n"] + 1
        run_id = "r-" + hashlib.sha1(f"{mid}|{mode}|{attempt}".encode()).hexdigest()[:8]
        t0 = time.time()
        base = {"run_id": run_id, "message_id": mid, "mode": mode, "audit_at": rt.store.now(), "entities": None, "relations": None, "no_link": None,
                "candidates": None, "proposal_ids": [], "provenance": {}, "model_versions": {}, "error": None, "refinement": None}
        if mode == "scripted" and scripted is None:
            app.update_message(mid, status="no_extraction", error="No scripted extraction exists for this message. Switch to Live to analyse it with the real models.")
            base["error"] = "no scripted extraction"
            app.save_analysis(base)
            return base
        try:
            if mode == "scripted":
                entities, relations, no_link, prov, versions, refinement, options = self._extract_scripted(message["text"], scripted)
            else:
                entities, relations, no_link, prov, versions, refinement, options = self._extract_live(message["text"])
            participants = app.participants()
            registry = participant_registry(participants)
            tz = app.settings().get("timezone")
            env = MessageEnvelope(mid, message["text"], message["sender_id"], message["recipient_ids"], message["created_at"], tz,
                                  message.get("thread_id", "default"), message.get("in_reply_to"))
            source = prov.get("relations", "rule")
            candidates = build_task_candidates(env, entities, relations, registry, primary_source=source, config=rt.reconciler.phase4_config)
            prov.update({"temporal": "rule", "identity": "rule", "reconciliation": "rule (cue-based)"})
            result = rt.reconciler.process_message(env, entities, candidates, registry, workspace_id=WORKSPACE, source_kind=source, options=options)
            base.update(entities=entities, relations=relations, no_link=no_link, candidates=[c.to_dict() for c in candidates],
                        proposal_ids=[p.proposal_id for p in result.proposals + result.no_actions], provenance=prov, model_versions=versions,
                        refinement=refinement)
            if refinement is not None:
                prov["refinement_preset"] = refinement["config"]["preset"]
            app.update_message(mid, status="analysed", error=None)
        except ModelUnavailable as e:
            base["error"] = f"Model unavailable: {e.reason}. Nothing was extracted."
            app.update_message(mid, status="analysis_failed", error=base["error"])
        except Exception as e:            # reported with its type, never swallowed silently
            base["error"] = f"{type(e).__name__}: {e}"
            app.update_message(mid, status="analysis_failed", error=base["error"])
        base["duration_ms"] = round((time.time() - t0) * 1000, 1)
        app.save_analysis(base)
        return base
