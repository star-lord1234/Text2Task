"""Orchestrates the refinement stages for one message. Pure: takes the raw neural entities, returns refined entities, rule relations, hints
for the reconciler and a trace. The raw input is never modified, and every new or changed span records where it came from."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from src.reconciliation.cues import split_sentences
from src.refine.clauses import ClauseDep, extract_clause_dependencies
from src.refine.config import RefineConfig
from src.refine.grammar import find_action_phrases, roster_mentions
from src.refine.spans import refine_spans, tag_neural, words_in
from src.refine.temporal import refine_temporal

MODEL_VERSION = "refine-v1"


@dataclass
class RefineResult:
    entities: list[dict[str, Any]]
    raw_entities: list[dict[str, Any]]
    relations: list[dict[str, Any]] = field(default_factory=list)      # rule-generated DEPENDS_ON between TASK entities
    hints: list[dict[str, Any]] = field(default_factory=list)          # clause hints for the reconciler (references to existing tasks)
    clause_deps: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    imperative_ids: list[str] = field(default_factory=list)            # TASK spans in the imperative mood: a request in itself (lets "Write a report." pass the Phase 5 gate)

    def to_dict(self) -> dict[str, Any]:
        return {"config": self.config, "raw_entities": self.raw_entities, "entities": self.entities, "rule_relations": self.relations,
                "clause_hints": self.hints, "clause_dependencies": self.clause_deps, "imperative_ids": self.imperative_ids, "trace": self.trace, "version": MODEL_VERSION}


def roster_map(participants: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in participants:
        name = str(p["name"]).strip().lower()
        out[name] = p["id"]
        out.setdefault(name.split()[0], p["id"])
    return out


def _overlap(a: int, b: int, c: int, d: int) -> int:
    return max(0, min(b, d) - max(a, c))


class _Ids:
    def __init__(self) -> None:
        self.n: dict[str, int] = {}

    def new(self, prefix: str) -> str:
        self.n[prefix] = self.n.get(prefix, 0) + 1
        return f"{prefix}{self.n[prefix]}"


def _recover(text: str, es: list[dict[str, Any]], cfg: RefineConfig, names: Sequence[str], roster: Mapping[str, str],
             trace: list[dict[str, Any]], ids: _Ids) -> list[dict[str, Any]]:
    """Step 4: roster vocatives/subjects, missing action phrases, dangling neural task spans."""
    out = list(es)
    taken = [(e["start"], e["end"]) for e in out]
    for s, e, pid in roster_mentions(text, dict(roster), taken):
        out.append({"id": ids.new("rule-p"), "type": "PERSON", "start": s, "end": e, "text": text[s:e], "confidence": None, "origin": "rule", "neural_ids": [],
                    "refinement": [{"op": "roster_name", "to": text[s:e], "rule": f"participant {pid} named as vocative or subject"}]})
        trace.append({"step": "grammar_recovery", "action": "added_person", "text": text[s:e]})
    protected = [(e["start"], e["end"]) for e in out if e["type"] in ("PERSON", "TEMPORAL")]
    for sent in split_sentences(text):
        for ph in find_action_phrases(text, sent.start, sent.end, protected=protected, names=names):
            out = _place_phrase(text, out, ph, ids, trace, step="grammar_recovery", allow_extend=True)
    return out


def _mark(e: dict[str, Any], ph) -> dict[str, Any]:
    return dict(e, grammar={"evidence": ph.evidence, "verb": ph.verb, "phrase": ph.text})


def _place_phrase(text, out, ph, ids, trace, *, step, allow_extend):
    """Attach an action phrase to the entity list: reuse a covering TASK span, join neural fragments of it, extend a dangling/prefix one, or add a new rule span."""
    from src.refine.lexicon import CLAUSE_CUE, DET, PREP
    tasks = [e for e in out if e["type"] == "TASK" and _overlap(e["start"], e["end"], ph.start, ph.end) > 0]
    if tasks:
        if len(tasks) == 1 and tasks[0]["start"] <= ph.start and tasks[0]["end"] >= ph.end:
            return [_mark(e, ph) if e is tasks[0] else e for e in out]            # already covered (kept as is, marked with the grammar evidence)
        if not allow_extend:
            return out
        # every overlapping neural span lies inside the phrase (allowing a leading 'please'/'let me'): they are fragments of ONE action phrase
        inside = [e for e in tasks if e["start"] >= ph.start - 20 and e["end"] <= ph.end]
        first = min(tasks, key=lambda e: e["start"])
        last_word = (text[first["start"]:first["end"]].split() or [""])[-1].lower().strip(".,;:")
        shape_ok = len(inside) == len(tasks) and (len(tasks) > 1 or last_word in (DET | PREP | CLAUSE_CUE) or first["end"] < ph.end)
        if shape_ok:
            lo, hi = min(e["start"] for e in tasks + [{"start": ph.start}]), max(e["end"] for e in tasks + [{"end": ph.end}])
            conf = [e.get("confidence") for e in tasks if e.get("confidence") is not None]
            new = {"id": first["id"], "type": "TASK", "start": lo, "end": hi, "text": text[lo:hi], "confidence": sum(conf) / len(conf) if conf else None,
                   "origin": "refined", "neural_ids": [i for e in tasks for i in e.get("neural_ids", [e["id"]])], "grammar": {"evidence": ph.evidence, "verb": ph.verb, "phrase": ph.text},
                   "refinement": list(first.get("refinement", [])) + [{"op": "extend_to_action_phrase", "from": [e["text"] for e in tasks], "to": text[lo:hi],
                                                                       "rule": f"{ph.evidence}; verb '{ph.verb}'"}]}
            trace.append({"step": step, "action": "extended", "from": [e["text"] for e in tasks], "to": new["text"]})
            return [new] + [e for e in out if e not in tasks]
        return out
    out = out + [{"id": ids.new("rule-k"), "type": "TASK", "start": ph.start, "end": ph.end, "text": ph.text, "confidence": None, "origin": "rule", "neural_ids": [],
                  "grammar": {"evidence": ph.evidence, "verb": ph.verb, "phrase": ph.text},
                  "refinement": [{"op": "recover_action_phrase", "to": ph.text, "rule": f"{ph.evidence}; verb '{ph.verb}'"}]}]
    trace.append({"step": step, "action": "recovered", "text": ph.text, "evidence": ph.evidence})
    return out


def _task_entity_for(out: list[dict[str, Any]], side) -> Optional[dict[str, Any]]:
    cover = [e for e in out if e["type"] == "TASK" and e["start"] < side.end and side.start < e["end"]]
    return cover[0] if cover else None


def refine(text: str, raw_entities: Sequence[Mapping[str, Any]], cfg: RefineConfig, participants: Sequence[Mapping[str, Any]] = ()) -> RefineResult:
    trace: list[dict[str, Any]] = []
    raw = tag_neural(raw_entities)
    res = RefineResult(entities=raw, raw_entities=[dict(e) for e in raw_entities], config=cfg.to_dict(), trace=trace)
    if not cfg.any_refinement:
        return res
    roster = roster_map(participants)
    names = list(roster)
    ids = _Ids()
    es = refine_spans(text, raw_entities, cfg, trace)
    es = refine_temporal(text, es, cfg, trace)
    if cfg.grammar_recovery:
        es = _recover(text, es, cfg, names, roster, trace, ids)
    if cfg.clause_dependencies:
        protected = [(e["start"], e["end"]) for e in es if e["type"] in ("PERSON", "TEMPORAL")]
        tasks = [e for e in es if e["type"] == "TASK"]
        deps = extract_clause_dependencies(text, split_sentences(text), tasks, protected, names)
        for d in deps:
            ents: dict[str, Optional[dict[str, Any]]] = {}
            for role, side in (("dependent", d.dependent), ("prerequisite", d.prerequisite)):
                if side.kind == "task" and side.phrase is not None:
                    es = _place_phrase(text, es, side.phrase, ids, trace, step="clause_dependencies", allow_extend=cfg.grammar_recovery)
                ents[role] = _task_entity_for(es, side) if side.kind == "task" else None
            res.clause_deps.append(d.to_dict())
            if d.prerequisite.kind == "reference":                      # task spans wholly inside a condition clause are fragments of it, not new tasks
                inside = [e for e in es if e["type"] == "TASK" and e["start"] >= d.prerequisite.start and e["end"] <= d.prerequisite.end]
                for e in inside:
                    trace.append({"step": "clause_dependencies", "action": "dropped", "id": e["id"], "text": e["text"], "reason": "inside a prerequisite reference clause"})
                es = [e for e in es if e not in inside]
            dep_e, pre_e = ents["dependent"], ents["prerequisite"]
            if d.dependent.kind == "task" and d.prerequisite.kind == "task" and dep_e and pre_e and dep_e["id"] != pre_e["id"]:
                res.relations.append({"source_id": dep_e["id"], "target_id": pre_e["id"], "label": "DEPENDS_ON", "score": None, "provenance": "rule",
                                      "rule": f"clause:{d.pattern}", "cue": d.cue, "evidence_text": d.sentence, "model_version": MODEL_VERSION})
                trace.append({"step": "clause_dependencies", "action": "relation", "pattern": d.pattern, "dependent": dep_e["text"], "prerequisite": pre_e["text"]})
            elif d.prerequisite.kind == "reference" or d.dependent.kind == "reference":
                res.hints.append({"pattern": d.pattern, "cue": d.cue, "dependent_entity_id": dep_e["id"] if dep_e else None,
                                  "dependent_range": [d.dependent.start, d.dependent.end], "prerequisite_range": [d.prerequisite.start, d.prerequisite.end],
                                  "prerequisite_text": text[d.prerequisite.start:d.prerequisite.end], "dependent_text": text[d.dependent.start:d.dependent.end],
                                  "kind": "reference_reference" if d.dependent.kind == "reference" else "task_reference", "evidence_text": d.sentence,
                                  "rule": f"clause:{d.pattern}"})
                trace.append({"step": "clause_dependencies", "action": "hint", "pattern": d.pattern, "prerequisite": text[d.prerequisite.start:d.prerequisite.end]})
    res.entities = sorted(es, key=lambda e: (e["start"], e["end"]))
    res.imperative_ids = [e["id"] for e in res.entities if e["type"] == "TASK" and (e.get("grammar") or {}).get("evidence") == "imperative/clause-start"]
    return res
