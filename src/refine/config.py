"""Independently switchable refinement stages and named presets for comparing neural-only, rule-based and hybrid runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping, Optional

STAGES = ("span_snap", "filter_invalid_tasks", "merge_adjacent", "temporal_detect", "temporal_merge", "grammar_recovery",
          "clause_dependencies", "context_lifecycle")


@dataclass(frozen=True)
class RefineConfig:
    entity_source: str = "neural"            # "neural" (checkpoint) or "rule" (the Phase 0 rule baseline; needs no model)
    span_snap: bool = False                  # step 2: extend a span that starts/ends inside a word to the word boundary
    filter_invalid_tasks: bool = False       # step 2: drop TASK spans made only of function words ("once", "the", "after you")
    merge_adjacent: bool = False             # step 2: merge same-type spans separated only by whitespace
    temporal_detect: bool = False            # step 3: independent regex detection of date/time expressions the model missed
    temporal_merge: bool = False             # step 3: merge compatible date/time/deadline-cue pieces into one expression
    grammar_recovery: bool = False           # step 4: closed-class chunker: recover action phrases, complete dangling ones, roster names
    clause_dependencies: bool = False        # step 5: clause-level dependency extraction from the raw text
    context_lifecycle: bool = False          # step 6: lifecycle/acknowledgement handling that does not need a TASK span
    rule_dependency_linker: bool = True      # the Phase 3 explicit-cue DEPENDS_ON rule over entity pairs (existing setting)
    preset: str = "custom"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def any_refinement(self) -> bool:
        return any(getattr(self, s) for s in STAGES)


_ALL = {s: True for s in STAGES}
PRESETS: dict[str, dict[str, Any]] = {
    # raw checkpoint output only (plus the Phase 4/5 rules that always run). No linker, no refinement.
    "neural_only": {"rule_dependency_linker": False},
    # what Phase 7 shipped: neural entities + the explicit-cue linker
    "neural_plus_linker": {"rule_dependency_linker": True},
    # steps 2-3: span/temporal repair only
    "refined": {"span_snap": True, "filter_invalid_tasks": True, "merge_adjacent": True, "temporal_detect": True, "temporal_merge": True,
                "rule_dependency_linker": True},
    # everything
    "hybrid": {**_ALL, "rule_dependency_linker": True},
    # no neural model: rule baseline spans + rule relations + the same downstream stages
    "rule_only": {"entity_source": "rule", "temporal_detect": True, "temporal_merge": True, "span_snap": True, "clause_dependencies": True,
                  "grammar_recovery": True, "context_lifecycle": True, "rule_dependency_linker": True},
}
PRESET_NOTES = {
    "neural_only": "Raw entity and relation model output. No rule dependency linker, no refinement.",
    "neural_plus_linker": "Neural output plus the explicit-cue dependency rule (the Phase 7 behaviour).",
    "refined": "Neural output with span snapping, invalid-fragment filtering, adjacent merging and temporal repair.",
    "hybrid": "All refinement stages: refined spans, grammar recovery, clause-level dependencies, context-aware lifecycle.",
    "rule_only": "No neural model: the rule baseline extracts spans, then the same rule stages run. Models are not loaded or needed.",
}
DEFAULT_PRESET = "hybrid"


def from_preset(name: str, **overrides: Any) -> RefineConfig:
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose one of {sorted(PRESETS)}")
    return RefineConfig(**{**PRESETS[name], **overrides, "preset": name})


def resolve(settings: Optional[Mapping[str, Any]]) -> RefineConfig:
    """Settings hold {"pipeline_preset": name, "refine_overrides": {stage: bool}, "rule_dependency_linker": bool}. Overrides win."""
    s = settings or {}
    name = s.get("pipeline_preset") or DEFAULT_PRESET
    names = {f.name for f in fields(RefineConfig)} - {"preset"}
    over = {k: v for k, v in (s.get("refine_overrides") or {}).items() if k in names}
    cfg = from_preset(name, **over)
    return RefineConfig(**{**cfg.to_dict(), "preset": name if not over else f"{name}+custom"})
