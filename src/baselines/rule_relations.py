"""Conservative rule comparator for relation linking (Phase 3).

Same output shape as the neural predictor, provenance "rule". Ambiguous cases are
returned under `unresolved`, never silently guessed. DEPENDS_ON here is the only
DEPENDS_ON path (no neural supervision exists), so it fires on explicit cues only.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

DEADLINE_CUE = re.compile(r"\b(by|before|due|no later than|until|deadline|end of (the )?day|close of business|cob|eod|prior to)\b", re.I)
PERSON_GAP = re.compile(
    r"^[\s,:;-]*(please|kindly|could you|can you|would you|will you|will|would|shall|should|must|needs? to|is to|are to|to|can|could)?[\s,]*$", re.I)
ASK_PREFIX = re.compile(r"\b(ask|tell|have|get|remind|want|need)\s+$", re.I)
SENT_BREAK = re.compile(r"[.!?]\s|\n")
DEP_CUE = re.compile(r"^[\s,]*(only\s+)?(after|once|when|following|depends? on|pending|contingent on|as soon as|until)\b[\s,]*(we\s+|you\s+|i\s+|they\s+)?(have\s+|has\s+)?(the\s+)?$", re.I)
MAX_TEMPORAL_DISTANCE = 120


def _same_sentence(text: str, a_end: int, b_start: int) -> bool:
    return not SENT_BREAK.search(text[a_end:b_start])


def _gap(text: str, a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[int, int]:
    return (a["end"], b["start"]) if a["end"] <= b["start"] else (b["end"], a["start"])


def _rel(src, tgt, label, rule, text, score=1.0):
    lo, hi = min(src["start"], tgt["start"]), max(src["end"], tgt["end"])
    return {"source_id": src["id"], "target_id": tgt["id"], "source_text": src["text"], "target_text": tgt["text"],
            "label": label, "score": score, "evidence_text": text[lo:hi], "rule": rule,
            "model_version": "rule-relations-v1", "provenance": "rule"}


def predict_rules(text: str, entities: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    tasks = [e for e in entities if e["type"] == "TASK"]
    persons = [e for e in entities if e["type"] == "PERSON"]
    temporals = [e for e in entities if e["type"] == "TEMPORAL"]
    relations, unresolved = [], []

    for task in tasks:
        # --- ASSIGNED_TO: addressee/subject adjacent to the task, same sentence.
        cands = []
        for p in persons:
            if p["end"] <= task["start"]:
                gap = text[p["end"]:task["start"]]
                if _same_sentence(text, p["end"], task["start"]) and PERSON_GAP.match(gap) and len(gap) <= 40:
                    cands.append((task["start"] - p["end"], p, "person_precedes_task"))
            elif task["start"] <= p["start"] and p["end"] <= task["end"]:
                before = text[task["start"]:p["start"]]
                if ASK_PREFIX.search(before):
                    cands.append((0, p, "ask_person_to"))
        if len(cands) == 1:
            relations.append(_rel(task, cands[0][1], "ASSIGNED_TO", cands[0][2], text))
        elif len(cands) > 1:
            cands.sort(key=lambda c: c[0])
            if cands[0][0] < cands[1][0]:
                relations.append(_rel(task, cands[0][1], "ASSIGNED_TO", cands[0][2], text))
            else:
                unresolved.append({"source_id": task["id"], "reason": "multiple_equally_close_assignees",
                                   "target_ids": [c[1]["id"] for c in cands], "provenance": "rule"})

        # --- DUE_ON vs SCHEDULED_ON: nearest same-sentence temporal; deadline cue decides label.
        near = []
        for t in temporals:
            lo, hi = _gap(text, task, t)
            overlap = not (t["end"] <= task["start"] or t["start"] >= task["end"])
            if overlap or (hi - lo <= MAX_TEMPORAL_DISTANCE and _same_sentence(text, lo, hi)):
                near.append((0 if overlap else hi - lo, t))
        near.sort(key=lambda c: c[0])
        for _, t in near[:1]:
            window = text[max(0, t["start"] - 25):t["end"]]
            label = "DUE_ON" if DEADLINE_CUE.search(window) else "SCHEDULED_ON"
            relations.append(_rel(task, t, label, "deadline_cue" if label == "DUE_ON" else "nearest_temporal", text))

    # --- DEPENDS_ON: "<task A> after/once <task B>" only with an explicit cue between adjacent tasks.
    ordered = sorted(tasks, key=lambda e: e["start"])
    for a, b in zip(ordered, ordered[1:]):
        gap = text[a["end"]:b["start"]]
        if len(gap) <= 40 and _same_sentence(text, a["end"], b["start"]) and DEP_CUE.match(gap):
            relations.append(_rel(a, b, "DEPENDS_ON", "explicit_prerequisite_cue", text))
    return {"relations": relations, "unresolved": unresolved}
