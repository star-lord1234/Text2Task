"""Rule-based uncertainty flags and clarification questions (Phase 4).

Relation scores are raw, UNCALIBRATED softmax values. They are only used against an explicit,
configurable threshold; with the default threshold 0.0 weak-score flagging is disabled.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from src.pipeline.contracts import AssigneeResolution, Flag, TemporalValue

DEADLINE_CUE = re.compile(r"\b(by|before|due|no later than|until|till|deadline|prior to|eod|cob|end of (?:the )?day|close of business)\b", re.I)
ASSUMPTIONS_NOTED = {"AMPM_INFERRED_BUSINESS_HOURS", "TIME_CONVENTION_APPLIED", "YEAR_INFERRED", "YEAR_INFERRED_FROM_WEEKDAY",
                     "US_DATE_ORDER", "DAY_FIRST_DATE_ORDER", "DATE_ASSUMED_REFERENCE_DAY", "END_OF_PERIOD", "RANGE_FROM_REFERENCE_DATE",
                     "NEXT_WEEKDAY_ISO_WEEK", "BOUND_AFTER", "WITHIN_WINDOW", "DST_GAP_ADJUSTED", "DST_AMBIGUOUS_TIME_FIRST_OCCURRENCE",
                     "TZ_FROM_REFERENCE_OFFSET", "MERGED_DATE_AND_TIME"} | {"MODIFIER_APPROXIMATED"}

TEMPLATES: dict[str, tuple[str, str]] = {
    "NO_ASSIGNEE": ("No owner could be determined for this task.", "Who should {task}?"),
    "AMBIGUOUS_ASSIGNEE": ("Several people could be the owner of this task.", "Which person should {task}: {candidates}?"),
    "UNKNOWN_PERSON": ("'{raw}' does not match any workspace participant.", "Who is '{raw}'? Is it one of the participants?"),
    "UNSUPPORTED_GROUP": ("'{raw}' is a group or collective; groups are not supported as owners.", "Which person is responsible for {task}?"),
    "MULTIPLE_ASSIGNEES": ("More than one owner was proposed ({raw}); no owner was chosen.", "Who is the single owner of {task}?"),
    "ASSIGNEE_BY_NAME_MATCH": ("Owner '{raw}' was matched to a participant by a unique name token.", "Is '{raw}' {candidates}?"),
    "DATE_UNRESOLVED_NO_ANCHOR": ("'{raw}' is relative and the message has no reference timestamp.", "What is the date of '{raw}'?"),
    "DATE_AMBIGUOUS": ("'{raw}' has more than one possible date ({candidates}).", "Which date did you mean for '{raw}' ({candidates})?"),
    "DATE_EVENT_CONDITION": ("'{raw}' depends on an event, not a calendar date.", "When is '{raw}' expected, or which task does it wait for?"),
    "DATE_VAGUE": ("'{raw}' is not a firm date.", "Is there a firm date for '{raw}'?"),
    "DATE_PARTIAL": ("'{raw}' is incomplete (missing {missing}).", "Which {missing} applies to '{raw}'?"),
    "DATE_UNPARSEABLE": ("'{raw}' could not be interpreted as a date or time.", "What date or time does '{raw}' refer to?"),
    "DATE_WEEKDAY_MISMATCH": ("The weekday and the calendar date in '{raw}' disagree.", "Which is right in '{raw}': the weekday or the date?"),
    "DATE_ASSUMPTION": ("Conventions were applied to '{raw}': {assumptions}.", "Is the interpretation of '{raw}' ({value}) correct?"),
    "DATE_RELATION_CONFLICT": ("'{raw}' reads like a deadline (cue: '{cue}') but was linked as {label}.", "Is '{raw}' a deadline or a scheduled time?"),
    "COMPETING_DATES": ("Several {label} dates were linked to this task ({raw}).", "Which date applies: {raw}?"),
    "PAST_DATE": ("'{raw}' resolves to a date before the message time.", "'{raw}' is in the past. Is this task already done?"),
    "WEAK_RELATION_SCORE": ("The link to '{raw}' has a low model score ({score:.2f}, uncalibrated).", "Is '{raw}' really linked to {task}?"),
    "MODEL_DISAGREEMENT": ("The neural and rule linkers disagree: {raw}.", "The extractors disagree about {task}. Which link is right?"),
    "UNSUPPORTED_PREREQUISITE": ("A prerequisite was proposed but no matching task exists ({raw}).", "Which task must happen before {task}?"),
    "TZ_ASSUMED": ("The message timestamp has no timezone, so values are floating (no offset).", "Which timezone applies to this workspace?"),
}
DEFAULT_SEVERITY = "warn"


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    path = path or Path(__file__).resolve().parents[2] / "configs" / "phase4.json"
    return json.loads(Path(path).read_text())


def make_flag(code: str, field: str, config: Mapping[str, Any], evidence: Optional[str] = None, **fmt: Any) -> Flag:
    message, question = TEMPLATES[code]
    sev = (config.get("uncertainty", {}).get("severities", {}) or {}).get(code, DEFAULT_SEVERITY)
    safe = {k: v for k, v in fmt.items()}
    safe.setdefault("task", "this task")
    for key in ("raw", "candidates", "missing", "assumptions", "value", "label", "cue", "score"):
        safe.setdefault(key, "" if key != "score" else 0.0)
    return Flag(code=code, severity=sev, field=field, message=message.format(**safe), question=question.format(**safe), evidence=evidence)


def assignee_flags(a: AssigneeResolution, task_title: str, config) -> list[Flag]:
    ev = a.basis
    t = task_title
    if a.status in ("RESOLVED", "RESOLVED_SENDER", "RESOLVED_RECIPIENT"):
        if a.basis in ("unique_name_token",):
            return [make_flag("ASSIGNEE_BY_NAME_MATCH", "assignee", config, ev, raw=a.raw or "", candidates=a.participant_id or "", task=t)]
        return []
    if a.status == "AMBIGUOUS":
        code = "MULTIPLE_ASSIGNEES" if a.basis == "multiple_assignees" else "AMBIGUOUS_ASSIGNEE"
        return [make_flag(code, "assignee", config, ev, raw=a.raw or "", candidates=", ".join(a.candidates), task=t)]
    if a.status == "UNKNOWN_PERSON":
        return [make_flag("UNKNOWN_PERSON", "assignee", config, ev, raw=a.raw or "", task=t)]
    if a.status == "UNSUPPORTED_GROUP":
        return [make_flag("UNSUPPORTED_GROUP", "assignee", config, ev, raw=a.raw or "", task=t)]
    if a.basis == "multiple_recipients":
        return [make_flag("AMBIGUOUS_ASSIGNEE", "assignee", config, ev, raw=a.raw or "", candidates=", ".join(a.candidates), task=t)]
    return [make_flag("NO_ASSIGNEE", "assignee", config, ev, task=t)]


def temporal_flags(tv: TemporalValue, field: str, label: str, context_before: str, config) -> list[Flag]:
    flags: list[Flag] = []
    raw = tv.raw
    s = tv.status
    if s == "UNRESOLVED_NO_ANCHOR":
        flags.append(make_flag("DATE_UNRESOLVED_NO_ANCHOR", field, config, tv.rule_id, raw=raw))
    elif s == "AMBIGUOUS":
        cands = ", ".join(c.get("date") or c.get("reading", "") for c in tv.candidates)
        flags.append(make_flag("DATE_AMBIGUOUS", field, config, tv.rule_id, raw=raw, candidates=cands))
    elif s == "UNRESOLVED_EVENT_CONDITION":
        flags.append(make_flag("DATE_EVENT_CONDITION", field, config, tv.rule_id, raw=raw))
    elif s == "VAGUE":
        flags.append(make_flag("DATE_VAGUE", field, config, tv.rule_id, raw=raw))
    elif s == "PARTIAL":
        missing = "date" if "DATE_MISSING" in tv.assumptions else "year" if "YEAR_MISSING" in tv.assumptions else "detail"
        flags.append(make_flag("DATE_PARTIAL", field, config, tv.rule_id, raw=raw, missing=missing))
    elif s == "UNPARSEABLE":
        flags.append(make_flag("DATE_UNPARSEABLE", field, config, tv.rule_id, raw=raw))
    if tv.in_past:
        flags.append(make_flag("PAST_DATE", field, config, tv.value or tv.start, raw=raw))
    if "WEEKDAY_DATE_MISMATCH" in tv.assumptions or "YEAR_INFERRED_WEEKDAY_MISMATCH" in tv.assumptions:
        flags.append(make_flag("DATE_WEEKDAY_MISMATCH", field, config, tv.rule_id, raw=raw))
    noted = sorted({a.split(":")[0] for a in tv.assumptions} & ASSUMPTIONS_NOTED)
    if noted and s in ("RESOLVED", "AMBIGUOUS"):
        flags.append(make_flag("DATE_ASSUMPTION", field, config, ",".join(tv.assumptions), raw=raw, assumptions=", ".join(noted), value=tv.value or f"{tv.start}..{tv.end}"))
    if "TZ_ASSUMED" in tv.assumptions:
        flags.append(make_flag("TZ_ASSUMED", field, config, None))
    # relation/label conflict: deadline cue but linked as SCHEDULED_ON
    if label == "SCHEDULED_ON":
        cue = DEADLINE_CUE.search(context_before[-30:] + " ") if context_before else None
        if tv.deadline_phrase and not cue:
            cue = DEADLINE_CUE.match(raw.lower())
        if tv.deadline_phrase or cue:
            cue_text = cue.group(0) if cue else "deadline phrase"
            flags.append(make_flag("DATE_RELATION_CONFLICT", field, config, cue_text, raw=raw, label=label, cue=cue_text))
    return flags


def deadline_cue_present(tv: TemporalValue, context_before: str) -> bool:
    return bool(tv.deadline_phrase or (context_before and DEADLINE_CUE.search(context_before[-30:] + " ")))


def review_required(flags: Sequence[Flag]) -> bool:
    return any(f.severity != "info" for f in flags)
