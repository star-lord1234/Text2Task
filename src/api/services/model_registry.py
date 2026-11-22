"""Model registry (Phase 7): loads the entity and relation checkpoints ONCE and reports what is ACTUALLY available.

A model that failed to load is reported as failed with its error; nothing here ever pretends a model is ready.
Factories are injectable so tests can use fakes without touching torch.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from src.api.config import Settings


class ModelUnavailable(Exception):
    def __init__(self, name: str, reason: str):
        super().__init__(f"{name} unavailable: {reason}")
        self.name, self.reason = name, reason


def _status(name: str, path: Path) -> dict[str, Any]:
    return {"name": name, "path": str(path), "status": "not_loaded", "available": False, "error": None, "loaded_in_s": None}


class ModelRegistry:
    def __init__(self, settings: Settings, entity_factory: Optional[Callable[[Path], Any]] = None,
                 relation_factory: Optional[Callable[[Path], Any]] = None):
        self.settings = settings
        self.entity_factory = entity_factory
        self.relation_factory = relation_factory
        self._entity: Any = None
        self._relation: Any = None
        self.info = {"entity": _status("entity extractor", settings.entity_model_dir), "relation": _status("relation classifier", settings.relation_model_dir)}

    def load(self) -> None:
        if not self.settings.load_models and self.entity_factory is None and self.relation_factory is None:
            for k in self.info:
                self.info[k].update(status="disabled", error="model loading disabled (T2T_NO_MODELS=1)")
            return
        self._load("entity", self.settings.entity_model_dir, self.entity_factory or self._default_entity)
        self._load("relation", self.settings.relation_model_dir, self.relation_factory or self._default_relation)

    def _load(self, key: str, path: Path, factory: Callable[[Path], Any]) -> None:
        info = self.info[key]
        info["status"] = "loading"
        t0 = time.time()
        try:
            if not Path(path).exists() and self.entity_factory is None and self.relation_factory is None:
                raise FileNotFoundError(f"checkpoint not found at {path}")
            obj = factory(path)
        except Exception as e:      # reported, never hidden
            info.update(status="failed", available=False, error=f"{type(e).__name__}: {e}")
            return
        setattr(self, f"_{key}", obj)
        info.update(status="loaded", available=True, error=None, loaded_in_s=round(time.time() - t0, 2), device=getattr(obj, "device", None))
        if key == "relation":
            info["version"] = getattr(obj, "version", None)
            info["labels"] = ["ASSIGNED_TO", "DUE_ON", "SCHEDULED_ON"]
        else:
            info["classes"] = ["TASK", "PERSON", "TEMPORAL"]

    @staticmethod
    def _default_entity(path: Path):
        from src.model_training.entity_inference import EntityPredictor
        return EntityPredictor(path)

    @staticmethod
    def _default_relation(path: Path):
        from src.model_training.relation_classifier import RelationPredictor
        return RelationPredictor(path)

    # ---------------------------------------------------------------- access
    def entity(self):
        if self._entity is None:
            raise ModelUnavailable("entity model", self.info["entity"].get("error") or self.info["entity"]["status"])
        return self._entity

    def relation(self):
        if self._relation is None:
            raise ModelUnavailable("relation model", self.info["relation"].get("error") or self.info["relation"]["status"])
        return self._relation

    def provenance_note(self) -> dict[str, Any]:
        active = self.settings.entity_model_dir.parents[1] / "ACTIVE_PROVISIONAL_MODEL.json"
        try:
            return json.loads(active.read_text())
        except Exception:
            return {}

    def capabilities(self, app_settings: dict[str, Any]) -> dict[str, Any]:
        ent, rel = dict(self.info["entity"]), dict(self.info["relation"])
        for d in (ent, rel):
            d["provisional"] = True
            d["provenance"] = "SILVER (MailEx-derived), not human-verified"
        from src.refine.config import PRESETS, PRESET_NOTES, from_preset, resolve
        fallback = bool(app_settings.get("allow_rule_fallback"))
        cfg = resolve(app_settings)
        rule_only = cfg.entity_source == "rule"            # the explicitly chosen rule-based pipeline needs no model
        live_ok = rule_only or ((ent["available"] or fallback) and (rel["available"] or fallback))
        return {
            "entity_model": ent, "relation_model": rel,
            "rule_fallback": {"available": True, "enabled": fallback, "covers": ["entity spans (rule baseline)", "relations (rule linker)"],
                              "note": "Opt-in. Used only when the matching neural model is unavailable, and always labelled 'rule'."},
            "pipeline": {"preset": cfg.preset, "config": cfg.to_dict(),
                         "presets": [{"name": n, "note": PRESET_NOTES[n], "config": from_preset(n).to_dict()} for n in PRESETS]},
            "rule_dependency_linker": {"enabled": bool(app_settings.get("rule_dependency_linker", True)),
                                       "note": "The neural relation model has no DEPENDS_ON class; explicit prerequisite wording is detected by rules and labelled 'rule'."},
            "modes": {"scripted": True, "live": bool(live_ok),
                      "live_reason": None if live_ok else "entity and/or relation model unavailable (rule fallback is off)"},
            "components": {"temporal": "rules", "identity": "rules", "reconciliation": "rules (cue-based, no trained matcher)", "graph": "NetworkX"},
        }
