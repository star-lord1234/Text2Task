"""Map MailEx human event annotations to Text2Task TASK / PERSON / TEMPORAL spans.

The mapping is deterministic and configured by ``configs/mailex_to_text2task_v1.json``.
Positions in MailEx are word-token indices into ``record["tokens"]``; they are
converted to character offsets with ``record["token_offsets"]`` (into ``record["text"]``).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

LABEL_RE_B = re.compile(r"^(?P<event>\w+):(?:\w+:\s*)?B-(?P<slot>.+)$")
LABEL_RE_I = re.compile(r"^\w+:(?:\w+:\s*)?I-")


def load_mapping(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_event_spans(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """All labeled argument spans: ``{event, slot, tok_start, tok_end}`` (end exclusive)."""
    spans: list[dict[str, Any]] = []
    for event_type, payload in (record.get("original_events") or {}).items():
        if event_type == "O":
            continue
        for row_index, labels in enumerate(payload.get("labels") or []):
            i = 0
            while i < len(labels):
                match = LABEL_RE_B.match(str(labels[i]))
                if not match:
                    i += 1
                    continue
                j = i + 1
                while j < len(labels) and LABEL_RE_I.match(str(labels[j])):
                    j += 1
                spans.append({
                    "event": event_type, "slot": match.group("slot").strip(),
                    "tok_start": i, "tok_end": j, "event_row": row_index,
                })
                i = j
    return spans


def char_range(record: Mapping[str, Any], tok_start: int, tok_end: int) -> tuple[int, int] | None:
    """Character range of a token span, ignoring zero-width (anomalous) tokens."""
    offsets = record["token_offsets"][tok_start:tok_end]
    real = [o for o in offsets if o[1] > o[0]]
    if not real:
        return None
    return int(real[0][0]), int(real[-1][1])


def is_person_name(surface: str, cfg: Mapping[str, Any]) -> bool:
    parts = surface.split()
    if not parts or len(parts) > int(cfg["max_tokens"]):
        return False
    token_re = re.compile(cfg["token_regex"])
    rejected = set(cfg["reject_tokens"])
    min_caps = int(cfg["reject_all_caps_min_length"])
    if len(parts) == 1 and len(parts[0].strip(".'-")) < int(cfg.get("min_single_token_length", 1)):
        return False
    for part in parts:
        if not token_re.match(part):
            return False
        bare = part.strip(".'-")
        if not bare or bare in rejected or bare.capitalize() in rejected:
            return False
        if len(bare) >= min_caps and bare.isupper():
            return False
        if cfg.get("reject_two_initial_caps") and re.match(r"^[A-Z]{2}", bare):
            return False
    return True


def is_event_clause_not_time(surface: str, cfg: Mapping[str, Any]) -> bool:
    """True for spans like 'Upon her approval' that name an event, not a date or time."""
    start, keep = cfg.get("clause_start_regex"), cfg.get("clause_keep_regex")
    if not start or not keep:
        return False
    text = surface.strip()
    return bool(re.match(start, text, re.IGNORECASE)) and not re.search(keep, text, re.IGNORECASE)


def is_commitment(surface: str, cfg: Mapping[str, Any]) -> bool:
    return re.match(cfg["commitment_pattern"], surface.strip(), re.IGNORECASE) is not None


def build_entities(
    record: Mapping[str, Any], mapping: Mapping[str, Any], *, include_commitments: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter]:
    """Return ``(entities, dropped, stats)`` for one unified MailEx record.

    Entities carry ``type``, ``start``, ``end``, ``text``, ``id`` and ``source``
    (the MailEx event/slot or ``propagated``).
    """
    text = record["text"]
    stats: Counter = Counter()
    dropped: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    task_cfg, temporal_cfg, person_cfg = mapping["task"], mapping["temporal"], mapping["person"]
    temporal_re = re.compile(temporal_cfg["slot_regex"])
    person_re = re.compile(person_cfg["slot_regex"])

    def add(kind: str, span: Mapping[str, Any], source: str) -> None:
        cr = char_range(record, span["tok_start"], span["tok_end"])
        if cr is None:
            stats[f"{kind}_dropped_zero_width"] += 1
            return
        entities.append({
            "type": kind, "start": cr[0], "end": cr[1], "text": text[cr[0]:cr[1]], "source": source,
        })
        stats[f"{kind}_kept"] += 1

    for span in parse_event_spans(record):
        event, slot = span["event"], span["slot"]
        length = span["tok_end"] - span["tok_start"]
        surface = None
        cr = char_range(record, span["tok_start"], span["tok_end"])
        if cr is not None:
            surface = text[cr[0]:cr[1]]
        source = f"{event}:{slot}"

        if slot == task_cfg["slot"] and any(event.startswith(p) for p in task_cfg["event_prefixes"]):
            add("TASK", span, source)
        elif (
            include_commitments and slot == task_cfg["slot"]
            and any(event.startswith(p) for p in task_cfg["commitment_event_prefixes"])
        ):
            if surface and is_commitment(surface, task_cfg):
                add("TASK", span, source + ":commitment")
            else:
                stats["commitment_candidates_rejected"] += 1
        elif temporal_re.search(slot):
            if length > int(temporal_cfg["max_tokens"]):
                stats["TEMPORAL_dropped_too_long"] += 1
                dropped.append({"reason": "temporal_too_long", "source": source, "text": surface})
            elif surface and is_event_clause_not_time(surface, temporal_cfg):
                stats["TEMPORAL_dropped_event_clause"] += 1
                dropped.append({"reason": "temporal_event_clause", "source": source, "text": surface})
            else:
                add("TEMPORAL", span, source)
        elif person_re.search(slot):
            if surface and is_person_name(surface, person_cfg):
                add("PERSON", span, source)
            else:
                stats["PERSON_rejected_not_a_name"] += 1

    if person_cfg.get("propagate_within_turn"):
        names = sorted({e["text"] for e in entities if e["type"] == "PERSON"}, key=len, reverse=True)
        for name in names:
            for match in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", text):
                s, e = match.span()
                if any(s < x["end"] and x["start"] < e for x in entities):
                    continue
                entities.append({"type": "PERSON", "start": s, "end": e, "text": name, "source": "propagated"})
                stats["PERSON_propagated"] += 1
    return entities, dropped, stats
