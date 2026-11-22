"""Step 3: independent temporal expression detection and merging of compatible pieces.

Detection is regex-based and knows nothing about the model. Atoms (weekday, relative day, date, time, part of day, period) are joined into one
expression only when they are compatible: at most one atom of each kind, an optional deadline/scope preposition in front ('by', 'before',
'until', 'on', 'at', 'for'), and joiners limited to whitespace, a comma, 'at', 'on', 'of' and '@'. Two dates ('Thursday and Friday') never merge."""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence

from src.refine.config import RefineConfig

MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WEEKDAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed|thu(?:rs?)?|fri)"
ATOMS: list[tuple[str, str]] = [
    ("DATE", rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b"),
    ("DATE", rf"\b\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b"),
    ("DATE", rf"\b{MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+\d{{4}})?"),
    ("DATE", rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTHS}\b(?:,?\s+\d{{4}})?"),
    ("DATE", rf"\b(?:the\s+)?day\s+after\s+tomorrow\b"),
    ("DATE", rf"\b(?:today|tomorrow|tonight|yesterday)\b"),
    ("DATE", rf"\b(?:next|this|last|coming|following)\s+(?:week|weekend|month|quarter|year)\b"),
    ("PART", rf"\b(?:end of (?:the )?day|eod|cob|close of business)\b"),
    ("DATE", rf"\b(?:end of (?:the )?(?:week|month|quarter|year)|eow|eom)\b"),
    ("DATE", rf"\b(?:in|within)\s+(?:an?|one|two|three|four|five|six|seven|\d+)\s+(?:minutes?|hours?|days?|weeks?|months?)\b"),
    ("DATE", rf"\b(?:(?:next|this|last|coming)\s+)?{WEEKDAY}\b"),
    ("TIME", rf"\b\d{{1,2}}(?::\d{{2}})?\s?(?:am|pm|a\.m\.|p\.m\.)(?![A-Za-z0-9])"),
    ("TIME", rf"\b(?:[01]?\d|2[0-3]):[0-5]\d\b"),
    ("TIME", rf"\b(?:noon|midnight)\b"),
    ("PART", rf"\b(?:morning|afternoon|evening|night)\b"),
]
ATOM_RX = [(k, re.compile(p, re.I)) for k, p in ATOMS]
LEAD = re.compile(r"(?<![A-Za-z0-9])(?:no later than|due on|due by|due|by|before|until|till|through|from|on|at|for)\s+$", re.I)
JOIN = re.compile(r"^\s*(?:,|@|\bat\b|\bon\b|\bof\b)?\s*$", re.I)


def detect(text: str) -> list[dict[str, Any]]:
    """Maximal compatible expressions, each {start, end, text, kinds, lead}."""
    atoms: list[tuple[int, int, str]] = []
    taken: list[tuple[int, int]] = []
    for kind, rx in ATOM_RX:                                     # earlier patterns win over later ones at the same place
        for m in rx.finditer(text):
            if any(m.start() < b and a < m.end() for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            atoms.append((m.start(), m.end(), kind))
    atoms.sort()
    exprs: list[dict[str, Any]] = []
    cur: Optional[dict[str, Any]] = None
    for a, b, kind in atoms:
        if cur and JOIN.match(text[cur["end"]:a]) and kind not in cur["kinds"] and not (kind == "TIME" and "TIME" in cur["kinds"]):
            if kind == "DATE" and "DATE" in cur["kinds"]:
                cur = None
            else:
                cur["end"] = b
                cur["kinds"].append(kind)
                continue
        cur = {"start": a, "end": b, "kinds": [kind]}
        exprs.append(cur)
    for x in exprs:                                              # attach one scope/deadline preposition immediately before
        w0 = max(0, x["start"] - 16)
        m = LEAD.search(text[w0:x["start"]])
        x["lead"] = m.group(0).strip() if m else None
        if m:
            x["start"] = w0 + m.start()
        x["text"] = text[x["start"]:x["end"]]
    return [x for x in exprs if x["text"].strip()]


def refine_temporal(text: str, entities: list[dict[str, Any]], cfg: RefineConfig, trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge neural TEMPORAL pieces into detected expressions (temporal_merge) and add expressions the model missed (temporal_detect)."""
    if not (cfg.temporal_detect or cfg.temporal_merge):
        return entities
    found = detect(text)
    out = list(entities)
    next_id = 1
    for x in found:
        over = [e for e in out if e["type"] == "TEMPORAL" and e["start"] < x["end"] and x["start"] < e["end"]]
        if over:
            if not cfg.temporal_merge:
                continue
            lo, hi = min([x["start"]] + [e["start"] for e in over]), max([x["end"]] + [e["end"] for e in over])
            extra = (text[lo:x["start"]] + text[x["end"]:hi]).strip()
            if len(extra.split()) > 2 or any(c in extra for c in ".?!;"):        # the model's span reaches far beyond: keep the model's
                continue
            if len(over) == 1 and (over[0]["start"], over[0]["end"]) == (lo, hi):
                continue                                                           # already exactly this expression
            keep = [e for e in out if e not in over]
            conf = [e.get("confidence") for e in over if e.get("confidence") is not None]
            merged = {"id": f"ref-t{next_id}", "type": "TEMPORAL", "start": lo, "end": hi, "text": text[lo:hi], "confidence": sum(conf) / len(conf) if conf else None,
                      "origin": "refined", "neural_ids": [i for e in over for i in e.get("neural_ids", [e["id"]])],
                      "refinement": [{"op": "merge_temporal", "from": [e["text"] for e in over], "to": text[lo:hi], "rule": "compatible date/time/deadline cue"}]}
            next_id += 1
            trace.append({"step": "temporal_merge", "action": "merged", "from": [e["text"] for e in over], "to": merged["text"]})
            out = keep + [merged]
        elif cfg.temporal_detect:
            if any(e["start"] < x["end"] and x["start"] < e["end"] for e in out):  # a different entity type already sits there
                continue
            out.append({"id": f"rule-t{next_id}", "type": "TEMPORAL", "start": x["start"], "end": x["end"], "text": x["text"], "confidence": None,
                        "origin": "rule", "neural_ids": [], "refinement": [{"op": "detect_temporal", "to": x["text"], "rule": "regex:" + "+".join(x["kinds"])}]})
            next_id += 1
            trace.append({"step": "temporal_detect", "action": "added", "text": x["text"]})
    return sorted(out, key=lambda e: (e["start"], e["end"]))
