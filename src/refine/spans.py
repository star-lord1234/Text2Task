"""Step 2: conservative span refinement. Pure functions over entity dicts; the neural output is never mutated.

Every returned entity carries `origin` and `refinement` (what was done and from which neural ids), so the Inspector can show raw vs refined.
Rules are generic (word boundaries, closed-class words); nothing mentions a specific example."""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence

from src.refine.config import RefineConfig
from src.refine.lexicon import AUX, CLAUSE_CUE, CLOSED, DET, PREP

WORD = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")
MAX_SNAP = 24                       # never extend a boundary by more than this many characters


def words_in(text: str, a: int, b: int) -> list[re.Match]:
    return [m for m in WORD.finditer(text, a, b)]


def tag_neural(entities: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy of the raw neural entities, labelled as such."""
    out = []
    for e in entities:
        c = dict(e)
        c.setdefault("origin", "neural")
        c.setdefault("refinement", [])
        c.setdefault("neural_ids", [e["id"]])
        out.append(c)
    return out


def _overlaps(a: int, b: int, c: int, d: int) -> bool:
    return a < d and c < b


def snap(text: str, entities: list[dict[str, Any]], trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A boundary inside a word moves to the word edge (sub-token truncation: 'ice' -> 'invoice'). Skipped when the extended span would
    run into another entity of a different type, or the move is larger than MAX_SNAP characters."""
    out = []
    for e in entities:
        s, t = e["start"], e["end"]
        ns, nt = s, t
        m = next((w for w in WORD.finditer(text, max(0, s - MAX_SNAP), s + 1) if w.start() < s < w.end()), None)
        if m:
            ns = m.start()
        m = next((w for w in WORD.finditer(text, max(0, t - 1), min(len(text), t + MAX_SNAP)) if w.start() < t < w.end()), None)
        if m:
            nt = m.end()
        if (ns, nt) != (s, t):
            clash = any(o is not e and o["type"] != e["type"] and _overlaps(ns, nt, o["start"], o["end"]) and not _overlaps(s, t, o["start"], o["end"]) for o in entities)
            if clash:
                trace.append({"step": "span_snap", "action": "skipped", "id": e["id"], "text": e["text"], "reason": "would overlap another entity"})
            else:
                c = dict(e, start=ns, end=nt, text=text[ns:nt], origin="refined", refinement=list(e.get("refinement", [])) + [
                    {"op": "snap_to_word", "from": e["text"], "to": text[ns:nt]}])
                trace.append({"step": "span_snap", "action": "extended", "id": e["id"], "from": e["text"], "to": text[ns:nt]})
                out.append(c)
                continue
        out.append(e)
    return out


def is_function_only(text: str) -> bool:
    ws = [w.group(0).lower() for w in WORD.finditer(text)]
    return not ws or all(w in CLOSED or len(w) <= 1 for w in ws)


def _bare_noun_phrase(text: str) -> bool:
    """'the meeting', 'the dataset': a determiner + noun(s) with no verb is an object fragment, not an action. Short and determiner-led only."""
    from src.refine.grammar import has_verb
    ws = [w.group(0).lower() for w in WORD.finditer(text)]
    return 0 < len(ws) <= 4 and ws[0] in (DET | PREP | CLAUSE_CUE) and not has_verb(text) and not any(w in AUX for w in ws)


def filter_invalid(text: str, entities: list[dict[str, Any]], trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A TASK span consisting only of function words/politeness/clause cues ('once', 'the', 'after you', 'only after', 'please', 'can') cannot be
    a task on its own. It is removed from the refined list (it stays visible in the raw neural output)."""
    out = []
    for e in entities:
        if e["type"] == "TASK" and is_function_only(e["text"]):
            trace.append({"step": "filter_invalid_tasks", "action": "dropped", "id": e["id"], "text": e["text"], "reason": "only function words"})
            continue
        if e["type"] == "TASK" and _bare_noun_phrase(e["text"]):
            trace.append({"step": "filter_invalid_tasks", "action": "dropped", "id": e["id"], "text": e["text"], "reason": "bare noun phrase without a verb"})
            continue
        out.append(e)
    return out


def merge_adjacent(text: str, entities: list[dict[str, Any]], trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same-type spans separated only by whitespace become one span ('send the' + 'invoice')."""
    ordered = sorted(entities, key=lambda e: (e["start"], e["end"]))
    out: list[dict[str, Any]] = []
    for e in ordered:
        prev = out[-1] if out else None
        touching = e["start"] < prev["end"] if prev else False                     # identical or overlapping spans (e.g. two fragments of one word after snapping)
        if prev and prev["type"] == e["type"] and e["type"] in ("TASK", "PERSON") and (touching or (e["start"] >= prev["end"] and not text[prev["end"]:e["start"]].strip())):
            hi = max(prev["end"], e["end"])
            merged = dict(prev, end=hi, text=text[prev["start"]:hi], origin="refined",
                          refinement=list(prev.get("refinement", [])) + [{"op": "merge_adjacent", "from": [prev["text"], e["text"]], "to": text[prev["start"]:hi]}],
                          neural_ids=list(prev.get("neural_ids", [])) + list(e.get("neural_ids", [e["id"]])))
            ids = [c for c in (prev["confidence"], e["confidence"]) if c is not None] if "confidence" in prev else []
            merged["confidence"] = sum(ids) / len(ids) if ids else None
            trace.append({"step": "merge_adjacent", "action": "merged", "from": [prev["text"], e["text"]], "to": merged["text"]})
            out[-1] = merged
        else:
            out.append(e)
    return out


def refine_spans(text: str, entities: Sequence[dict[str, Any]], cfg: RefineConfig, trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    es = tag_neural(entities)
    if cfg.span_snap:
        es = snap(text, es, trace)
    if cfg.filter_invalid_tasks:
        es = filter_invalid(text, es, trace)
    if cfg.merge_adjacent:
        es = merge_adjacent(text, es, trace)
    return es
