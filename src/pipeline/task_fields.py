"""Assemble TaskCandidate records from entities + relations (Phase 4).

Every TASK span becomes a candidate; unresolved fields are kept (never dropped or guessed).
Primary relations come from one source ("neural" by default, "rule" only when explicitly
requested); an optional comparator source only produces MODEL_DISAGREEMENT flags and
rule-only DEPENDS_ON proposals.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Mapping, Optional, Sequence

from src.pipeline.contracts import AssigneeResolution, Flag, MessageEnvelope, TaskCandidate, TemporalValue
from src.pipeline.identity_resolution import ParticipantRegistry, resolve_assignee
from src.pipeline.uncertainty import (assignee_flags, deadline_cue_present, load_config, make_flag,
                                      review_required, temporal_flags)
from src.temporal.normalize import normalize_temporal

TEMPORAL_LABELS = ("DUE_ON", "SCHEDULED_ON")
CONTEXT_CHARS = 40


def _title(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"^(please|kindly)\s+", "", t, flags=re.I)
    return t.strip(" ,.;:")


def _merge_date_time(a: TemporalValue, b: TemporalValue, envelope, cfg) -> Optional[TemporalValue]:
    """Merge a date-only value with a time-only value linked to the same task and relation."""
    date_tv, time_tv = (a, b) if b.granularity == "TIME_ONLY" else (b, a)
    if time_tv.granularity != "TIME_ONLY" or date_tv.granularity not in ("DATE", "PART_OF_DAY"):
        return None
    time_raw = re.sub(r"^(at|@)\s+", "", time_tv.raw.strip(), flags=re.I)
    merged = normalize_temporal(f"{date_tv.raw} at {time_raw}", reference_ts=envelope.timestamp,
                                timezone=envelope.timezone, config=cfg.get("temporal"))
    if merged.status != "RESOLVED" or merged.granularity != "DATETIME":
        return None
    merged.raw = f"{date_tv.raw} + {time_tv.raw}"
    merged.assumptions.append("MERGED_DATE_AND_TIME")
    merged.deadline_phrase = date_tv.deadline_phrase or time_tv.deadline_phrase
    return merged


def _score(rel: Mapping[str, Any]) -> Optional[float]:
    """A relation's model score, or None when it has none (scripted fixtures, rules). None means 'unknown', never a made-up number."""
    v = rel.get("score")
    return None if v is None else float(v)


def _rel_view(rels: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    return {(r["label"], r["target_id"]) for r in rels if r["label"] != "DEPENDS_ON"}


def build_task_candidates(envelope: MessageEnvelope, entities: Sequence[Mapping[str, Any]],
                          primary_relations: Sequence[Mapping[str, Any]], registry: ParticipantRegistry,
                          *, primary_source: str = "neural", comparator_relations: Optional[Sequence[Mapping[str, Any]]] = None,
                          config: Optional[Mapping[str, Any]] = None) -> list[TaskCandidate]:
    cfg = dict(config) if config is not None else load_config()
    by_id = {e["id"]: e for e in entities}
    tasks = sorted((e for e in entities if e["type"] == "TASK"), key=lambda e: e["start"])
    candidate_ids = {t["id"]: f"{envelope.message_id}::task::{t['id']}" for t in tasks}
    min_score = float(cfg.get("uncertainty", {}).get("min_relation_score", 0.0) or 0.0)
    out: list[TaskCandidate] = []

    rels_by_task: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in primary_relations:
        rels_by_task[r["source_id"]].append(r)
    comp_by_task: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in comparator_relations or []:
        comp_by_task[r["source_id"]].append(r)

    for task in tasks:
        title = _title(task["text"])
        flags: list[Flag] = []
        rels = rels_by_task.get(task["id"], [])

        # ---- assignee
        persons = [by_id[r["target_id"]] for r in rels if r["label"] == "ASSIGNED_TO" and r["target_id"] in by_id]
        assignee = resolve_assignee(persons, task, envelope, registry)
        flags += assignee_flags(assignee, title, cfg)

        # ---- temporal values per relation label
        fields: dict[str, Optional[TemporalValue]] = {"DUE_ON": None, "SCHEDULED_ON": None}
        applied_notes: list[dict[str, Any]] = []
        grouped: dict[str, list[tuple[Mapping[str, Any], TemporalValue, str]]] = defaultdict(list)
        for r in rels:
            if r["label"] not in TEMPORAL_LABELS or r["target_id"] not in by_id:
                continue
            ent = by_id[r["target_id"]]
            tv = normalize_temporal(ent["text"], reference_ts=envelope.timestamp, timezone=envelope.timezone,
                                    relation_hint=r["label"], config=cfg.get("temporal"))
            prev_end = max([e["end"] for e in entities if e["end"] <= ent["start"]], default=0)
            before = envelope.text[max(prev_end, ent["start"] - CONTEXT_CHARS):ent["start"]]
            grouped[r["label"]].append((r, tv, before))

        for label, items in grouped.items():
            items.sort(key=lambda x: -(_score(x[0]) or 0.0))
            chosen_rel, chosen_tv, chosen_before = items[0]
            rest = items[1:]
            # merge a date with a separate time expression linked to the same task and relation
            for other in list(rest):
                merged = _merge_date_time(chosen_tv, other[1], envelope, cfg)
                if merged is not None:
                    chosen_tv = merged
                    rest.remove(other)
                    break
            if rest:
                raws = " / ".join([chosen_tv.raw] + [x[1].raw for x in rest])
                flags.append(make_flag("COMPETING_DATES", f"{'due' if label == 'DUE_ON' else 'scheduled'}", cfg,
                                       raws, raw=raws, label=label))
            applied = label
            if label == "SCHEDULED_ON" and deadline_cue_present(chosen_tv, chosen_before):
                applied = "DUE_ON"   # proposed reading; model label kept in provenance and flagged below
                applied_notes.append({"model_label": label, "applied_label": applied, "reason": "deadline_cue",
                                      "raw": chosen_tv.raw})
            target_field = "due" if applied == "DUE_ON" else "scheduled"
            if fields[applied] is None:
                fields[applied] = chosen_tv
            else:
                flags.append(make_flag("COMPETING_DATES", target_field, cfg, chosen_tv.raw,
                                       raw=f"{fields[applied].raw} / {chosen_tv.raw}", label=applied))
            flags += temporal_flags(chosen_tv, target_field, label, chosen_before, cfg)

        # ---- weak scores (disabled while min_relation_score == 0)
        if min_score > 0:
            for r in rels:
                sc = _score(r)
                if r["label"] != "DEPENDS_ON" and sc is not None and sc < min_score and r["target_id"] in by_id:
                    flags.append(make_flag("WEAK_RELATION_SCORE", "relations", cfg, f"score={sc}",
                                           raw=by_id[r["target_id"]]["text"], score=sc, task=title))

        # ---- neural vs rule disagreement
        if comparator_relations is not None:
            a, b = _rel_view(rels), _rel_view(comp_by_task.get(task["id"], []))
            if a != b:
                def show(s):
                    return ", ".join(sorted(f"{l}->{by_id[t]['text'] if t in by_id else t}" for l, t in s)) or "no link"
                flags.append(make_flag("MODEL_DISAGREEMENT", "relations", cfg, None,
                                       raw=f"{primary_source}: [{show(a - b)}] vs other: [{show(b - a)}]", task=title))

        # ---- dependencies (rule path only; proposed, never accepted here)
        deps = []
        for r in list(rels) + list(comp_by_task.get(task["id"], [])):
            if r["label"] != "DEPENDS_ON":
                continue
            target = r["target_id"]
            if target in candidate_ids:
                deps.append({"relation": "DEPENDS_ON", "prerequisite_candidate_id": candidate_ids[target],
                             "status": "proposed", "provenance": r.get("provenance", "rule"),
                             "evidence_text": r.get("evidence_text")})
            else:
                flags.append(make_flag("UNSUPPORTED_PREREQUISITE", "dependencies", cfg, None,
                                       raw=by_id.get(target, {}).get("text", target), task=title))

        # ---- conflicting-label flags go once per temporal value; add the conflict note to provenance
        rel_provenance = [{"label": r["label"], "target_id": r["target_id"], "score": r.get("score"),
                           "provenance": r.get("provenance", primary_source), "model_version": r.get("model_version")}
                          for r in rels]
        out.append(TaskCandidate(
            candidate_id=candidate_ids[task["id"]], message_id=envelope.message_id, title=title,
            task_span={k: task[k] for k in ("id", "start", "end", "text")},
            assignee=assignee, due=fields["DUE_ON"], scheduled=fields["SCHEDULED_ON"], dependencies=deps,
            flags=flags, review_required=review_required(flags),
            provenance={"relation_source": primary_source, "relations": rel_provenance,
                        "label_reinterpretations": applied_notes,
                        "reference_timestamp": envelope.timestamp, "timezone": envelope.timezone,
                        "registry_low_trust": any(p.low_trust for p in registry.participants)},
            evidence_text=envelope.text[max(0, task["start"] - 60):task["end"] + 60].strip()))
    return out
