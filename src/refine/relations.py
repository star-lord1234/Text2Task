"""Step 4 (assignees): clause scoping of ASSIGNED_TO relations and rule-based recovery of a missing one.

The relation model scores every TASK/PERSON pair independently, so in 'Bianca, train the model, then Anushree should evaluate it' both people can
be linked to both tasks. When a task has several candidate owners, those separated from it by a clause boundary ('then', ';', once/after/before...)
are dropped if another candidate is not. When a task has no owner link, a person directly before it as vocative or subject ('Bianca, please X',
'Anushree should X') is linked by rule. Every change is recorded; the model's original relations are kept elsewhere."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

BOUNDARY = re.compile(r";|\bthen\b|\b(?:once|after|before|when|whenever|until|because|since|unless|while)\b", re.I)
LEAD_WORDS = {"please", "can", "could", "would", "will", "you", "should", "must", "to", "need", "needs", "has", "have", "shall", "let", "kindly", "just", "also", "ll", "i", "we"}


def _between(text: str, a: Mapping[str, Any], b: Mapping[str, Any]) -> str:
    lo, hi = sorted([(a["start"], a["end"]), (b["start"], b["end"])])
    return text[lo[1]:hi[0]]


def refine_relations(text: str, entities: Sequence[Mapping[str, Any]], relations: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {e["id"]: e for e in entities}
    edits: list[dict[str, Any]] = []
    out = [dict(r) for r in relations]
    for task in (e for e in entities if e["type"] == "TASK"):
        owned = [r for r in out if r["source_id"] == task["id"] and r["label"] == "ASSIGNED_TO" and r["target_id"] in by_id]
        if len(owned) > 1:
            sep = {r["target_id"]: bool(BOUNDARY.search(_between(text, task, by_id[r["target_id"]]))) for r in owned}
            if not all(sep.values()):
                for r in owned:
                    if sep[r["target_id"]]:
                        out.remove(r)
                        edits.append({"op": "drop_cross_clause_owner", "task": task["text"], "person": by_id[r["target_id"]]["text"], "model_score": r.get("score")})
    for task in (e for e in entities if e["type"] == "TASK"):
        if any(r["source_id"] == task["id"] and r["label"] == "ASSIGNED_TO" for r in out):
            continue
        before = [e for e in entities if e["type"] == "PERSON" and e["end"] <= task["start"]]
        if not before:
            continue
        p = max(before, key=lambda e: e["end"])
        gap = text[p["end"]:task["start"]]
        words = re.findall(r"[A-Za-z']+", gap.lower())
        if all(w in LEAD_WORDS for w in words) and not re.search(r"[.;!?]", gap) and not BOUNDARY.search(gap):
            out.append({"source_id": task["id"], "target_id": p["id"], "label": "ASSIGNED_TO", "score": None, "provenance": "rule",
                        "rule": "vocative_or_subject_before_task", "model_version": "refine-v1"})
            edits.append({"op": "add_owner", "task": task["text"], "person": p["text"], "rule": "vocative_or_subject_before_task"})
    return out, edits
