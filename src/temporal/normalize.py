"""Deterministic temporal normalisation (Phase 4).

Principles
- Never read the machine clock. Relative expressions need an explicit reference timestamp,
  otherwise they stay UNRESOLVED_NO_ANCHOR.
- Never invent a date, a clock time, or a year silently: every convention applied is
  recorded in ``assumptions``; ambiguity is returned as AMBIGUOUS with candidates.
- Raw text is always preserved.

Conventions (documented, tested, configurable where noted)
- Weeks are ISO weeks (Mon-Sun). Bare weekday = next occurrence strictly after the reference
  date; the same weekday as the reference date is AMBIGUOUS (today vs. +7). ``this X`` = X in
  the current ISO week, ``next X`` = X in the next ISO week, ``last X`` = X in the previous one.
- ``m/d/y`` is read US-style unless the first number exceeds 12 (assumption recorded).
- Bare hours without am/pm use a business-hours reading (7-11 AM, 12-6 PM) and record it.
- EOD/COB/end of day = ``eod_hour`` (default 17:00), recorded as TIME_CONVENTION_APPLIED.
- A missing year is inferred as the nearest upcoming occurrence only when an anchor exists.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone as _tz
from email.utils import parsedate_to_datetime
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.pipeline.contracts import TemporalValue

DEFAULT_CONFIG: dict[str, Any] = {
    "eod_hour": 17, "eod_minute": 0, "bare_weekday_same_day": "ambiguous",
    "business_hours_ampm": True, "default_timezone": None,
}

_M = ("january february march april may june july august september october november december").split()
MONTHS = {m: i + 1 for i, m in enumerate(_M)}
MONTHS.update({m[:3]: i + 1 for i, m in enumerate(_M)})
MONTHS["sept"] = 9
_W = "monday tuesday wednesday thursday friday saturday sunday".split()
WEEKDAYS = {w: i for i, w in enumerate(_W)}
WEEKDAYS.update({w[:3]: i for i, w in enumerate(_W)})
WEEKDAYS.update({"tues": 1, "thur": 3, "thurs": 3})
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
PARTS = ("morning", "afternoon", "evening", "night")

_MON = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
_WD = "(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\.?"
_ORD = r"(?:st|nd|rd|th)?"
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?"

DEADLINE_PREFIX = re.compile(r"^(by|before|due(?: on| by)?|no later than|until|till|prior to|deadline)\b\s*", re.I)
LOOSE_PREFIX = re.compile(r"^(on|to|around|about|approximately|approx\.?|from|the|at|for|over|during|beginning at|starting at|beginning|starting)\s+", re.I)
MODIFIER_PREFIX = re.compile(r"^(sometime|some time|early|late|mid-?)\s+(?=\S)", re.I)
CLAUSE_RE = re.compile(r"^(as|at the time|at which point|at that point|while|since)\b", re.I)
DURATION_RE = re.compile(r"^(approximately\s+|about\s+)?(\d+(?:\s*-\s*\d+)?|a|an|one|two|three|four|five)\s*(min|mins|minutes?|hr|hrs|hours?|days?|weeks?|months?)$|^all day$", re.I)
WITHIN_RE = re.compile(r"^within\s+(?:the\s+)?(?:next\s+)?(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s+(hour|day|week|month)s?$")
EVENT_PREFIX = re.compile(r"^(as soon as|once|when|upon|pending|contingent on|whenever|assuming|if)\b", re.I)
AFTER_PREFIX = re.compile(r"^(after|following)\s+", re.I)
VAGUE_RE = re.compile(r"^(soon|asap|a\.s\.a\.p\.?|as soon as possible|shortly|eventually|in the near future|at some point|"
                      r"sometime|some time|later|when possible|right away|immediately|promptly|urgent(?:ly)?|"
                      r"at your earliest convenience|in due course|ongoing|next time|at the time|that time|that day|then)$", re.I)
RECURRING_RE = re.compile(r"\b(every|each|weekly|daily|monthly|annually|yearly|biweekly|fortnightly)\b", re.I)


class _Ctx:
    def __init__(self, reference_ts, timezone_name, config):
        self.cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.assumptions: list[str] = []
        self.tz = None
        tzname = timezone_name or self.cfg.get("default_timezone")
        if tzname:
            try:
                self.tz = ZoneInfo(tzname)
            except (ZoneInfoNotFoundError, ValueError):
                self.assumptions.append("TIMEZONE_UNKNOWN")
        self.ref: Optional[datetime] = None
        self.floating = False
        ref = _parse_reference(reference_ts)
        if reference_ts not in (None, "") and ref is None:
            self.assumptions.append("REFERENCE_UNPARSEABLE")
        if ref is not None:
            if ref.tzinfo is not None:
                if self.tz is not None:
                    ref = ref.astimezone(self.tz)
                else:
                    self.tz = ref.tzinfo
                    self.assumptions.append("TZ_FROM_REFERENCE_OFFSET")
            elif self.tz is not None:
                ref = ref.replace(tzinfo=self.tz)
            else:
                self.floating = True
            self.ref = ref
        self.anchor_used = False

    @property
    def has_anchor(self) -> bool:
        return self.ref is not None

    def ref_date(self) -> date:
        self.anchor_used = True
        return self.ref.date()


def _parse_reference(value) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None


def _iso(d) -> str:
    return d.isoformat()


def _expand_year(y: int) -> int:
    return y if y >= 100 else (2000 + y if y < 70 else 1900 + y)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _end_of_month(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)


def _add_months(d: date, n: int) -> date:
    m0 = d.month - 1 + n
    y, m = d.year + m0 // 12, m0 % 12 + 1
    return date(y, m, min(d.day, _end_of_month(y, m).day))


def _num(token: str) -> Optional[int]:
    token = token.lower()
    return int(token) if token.isdigit() else NUMBER_WORDS.get(token)


# --------------------------------------------------------------------------- time parsing
def _parse_time(s: str, ctx: _Ctx):
    """Return (time, end_time|None, assumptions) or None for a time-of-day expression."""
    s = s.strip().lower()
    asm: list[str] = []
    if s in ("noon", "midday", "12 noon"):
        return time(12, 0), None, asm
    if s == "midnight":
        return time(0, 0), None, asm
    if re.fullmatch(r"(eod|cob|e\.o\.d\.?|end of (?:the )?(?:business )?day|close of business|end of business|close of play)", s):
        asm.append("TIME_CONVENTION_APPLIED")
        return time(ctx.cfg["eod_hour"], ctx.cfg["eod_minute"]), None, asm
    m = re.fullmatch(rf"{_TIME}\s*(?:-|–|to|until)\s*{_TIME}", s)
    if m:
        h1, mi1, ap1, h2, mi2, ap2 = m.groups()
        ap1 = ap1 or ap2
        a = _build_time(h1, mi1, ap1, ctx, asm, need_marker=False)
        b = _build_time(h2, mi2, ap2, ctx, asm, need_marker=False)
        if a and b:
            return a, b, asm
        return None
    m = re.fullmatch(_TIME, s)
    if m:
        h, mi, ap = m.groups()
        t = _build_time(h, mi, ap, ctx, asm, need_marker=False)
        return (t, None, asm) if t else None
    return None


def _build_time(h, mi, ap, ctx, asm, need_marker=False):
    hour, minute = int(h), int(mi) if mi else 0
    if minute > 59:
        return None
    if ap:
        ap = ap.replace(".", "")
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ap == "pm" else 0)
    elif hour > 24 or (hour == 24 and minute):
        return None
    elif hour <= 12 and ctx.cfg["business_hours_ampm"] and not (len(h) == 2 and h.startswith("0")):
        if hour < 7:
            hour += 12  # 1-6 read as afternoon; 7-11 morning; 12 noon
        asm.append("AMPM_INFERRED_BUSINESS_HOURS")
    if hour == 24:
        hour = 0
    return time(hour, minute)


_TIME_MARKED = rf"(?:\d{{1,2}}(?::\d{{2}})?\s*(?:a\.?m\.?|p\.?m\.?)|\d{{1,2}}:\d{{2}}|noon|midnight)"
_TIME_NC = r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?"
_TIME_RANGE_MARKED = rf"(?:{_TIME_NC}\s*(?:-|–|to)\s*)?{_TIME_MARKED}"
_TRAIL_AT = re.compile(rf"^(.*?)[\s,]+(?:at|@)\s+(.+)$")
_TRAIL_MARKED = re.compile(rf"^(.*?)[\s,]+({_TIME_RANGE_MARKED}|eod|cob|end of (?:the )?day|close of business)$")
_LEAD_MARKED = re.compile(rf"^({_TIME_RANGE_MARKED}|eod|cob|close of business|end of (?:the )?day)[\s,]+(?:on\s+)?(.+)$")


def _split_time(s: str):
    """Split 'date + time' into (date_text, time_text) when a time component is present."""
    m = _TRAIL_AT.match(s)
    if m and _parse_time_loose(m.group(2)):
        return m.group(1), m.group(2)
    m = _TRAIL_MARKED.match(s)
    if m:
        return m.group(1), m.group(2)
    m = _LEAD_MARKED.match(s)
    if m:
        return m.group(2), m.group(1)
    return None


def _parse_time_loose(s: str) -> bool:
    return bool(re.fullmatch(rf"(?:{_TIME_RANGE_MARKED}|{_TIME}(?:\s*(?:-|–|to)\s*{_TIME})?|eod|cob|noon|midnight|end of (?:the )?day|close of business)", s.strip().lower()))


# --------------------------------------------------------------------------- date parsing
class _R:
    """Intermediate result of a date-part parse."""

    def __init__(self, kind, rule, status="RESOLVED", start=None, end=None, part=None, candidates=None,
                 assumptions=None, needs_anchor=False):
        self.kind, self.rule, self.status = kind, rule, status
        self.start, self.end, self.part = start, end, part
        self.candidates = candidates or []
        self.assumptions = assumptions or []
        self.needs_anchor = needs_anchor


def _no_anchor(rule: str) -> _R:
    return _R("none", rule, status="UNRESOLVED_NO_ANCHOR", needs_anchor=True)


def _infer_year(month: int, day: int, ctx: _Ctx, weekday: Optional[int]):
    """Nearest upcoming occurrence on/after the reference date. A weekday narrows the choice
    to years within +-1 of the reference year; if none matches, fall back and flag the mismatch."""
    ref = ctx.ref_date()

    def valid(y):
        try:
            return date(y, month, day)
        except ValueError:
            return None

    if weekday is not None:
        options = [d for d in (valid(y) for y in range(ref.year - 1, ref.year + 2)) if d and d.weekday() == weekday]
        if options:
            upcoming = [d for d in options if d >= ref]
            pick = min(upcoming) if upcoming else max(options)
            return pick, "YEAR_INFERRED_FROM_WEEKDAY"
    options = [d for d in (valid(y) for y in (ref.year, ref.year + 1)) if d]
    if not options:
        return None, None
    upcoming = [d for d in options if d >= ref]
    pick = min(upcoming) if upcoming else max(options)
    return pick, ("YEAR_INFERRED" if weekday is None else "YEAR_INFERRED_WEEKDAY_MISMATCH")


def _parse_absolute(s: str, ctx: _Ctx) -> Optional[_R]:
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return _mk_date(int(m[1]), int(m[2]), int(m[3]), "abs_iso", [])
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), _expand_year(int(m[3]))
        asm = ["US_DATE_ORDER"]
        if a > 12 >= b:
            a, b, asm = b, a, ["DAY_FIRST_DATE_ORDER"]
        return _mk_date(y, a, b, "abs_slash", asm)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", s)
    if m:
        a, b = int(m[1]), int(m[2])
        asm = ["US_DATE_ORDER"]
        if a > 12 >= b:
            a, b, asm = b, a, ["DAY_FIRST_DATE_ORDER"]
        return _partial_md(a, b, None, ctx, "abs_slash_md", asm)
    m = re.fullmatch(rf"(\d{{1,2}})-{_MON}-(\d{{2,4}})", s)
    if m:
        return _mk_date(_expand_year(int(m[3])), MONTHS[m[2]], int(m[1]), "abs_dmy_dash", [])
    wd = rf"(?:{_WD},?\s+)?"
    m = re.fullmatch(rf"{wd}{_MON}\s+(\d{{1,2}}){_ORD}(?:,?\s+{_WD})?(?:,?\s+(\d{{4}}))?", s)
    if m:
        w = WEEKDAYS[m[1]] if m[1] else (WEEKDAYS[m[4]] if m[4] else None)
        mon, day, y = MONTHS[m[2]], int(m[3]), m[5]
        return _month_day(mon, day, int(y) if y else None, w, ctx, "abs_month_day")
    m = re.fullmatch(rf"(?:in\s+)?{_MON}\s+of\s+(\d{{4}})", s)
    if m:
        y, mon = int(m[2]), MONTHS[m[1]]
        return _R("month", "abs_month_year", start=date(y, mon, 1), end=_end_of_month(y, mon))
    m = re.fullmatch(rf"{wd}(\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MON}(?:,?\s+(\d{{4}}))?", s)
    if m:
        w = WEEKDAYS[m[1]] if m[1] else None
        return _month_day(MONTHS[m[3]], int(m[2]), int(m[4]) if m[4] else None, w, ctx, "abs_day_month")
    m = re.fullmatch(rf"{_MON}\s+(\d{{1,2}}){_ORD}\s*(?:-|–|to|through|thru)\s*(?:{_MON}\s+)?(\d{{1,2}}){_ORD}(?:,?\s+(\d{{4}}))?", s)
    if m:
        m1 = MONTHS[m[1]]
        m2 = MONTHS[m[3]] if m[3] else m1
        a = _month_day(m1, int(m[2]), int(m[5]) if m[5] else None, None, ctx, "abs_range")
        b = _month_day(m2, int(m[4]), int(m[5]) if m[5] else None, None, ctx, "abs_range")
        if a.status != "RESOLVED" or b.status != "RESOLVED":
            return a if a.status != "RESOLVED" else b
        return _R("range", "abs_range", start=a.start, end=b.start, assumptions=a.assumptions + b.assumptions)
    m = re.fullmatch(rf"(?:in\s+)?{_MON},?\s+(\d{{4}})", s)
    if m:
        y, mon = int(m[2]), MONTHS[m[1]]
        return _R("month", "abs_month_year", start=date(y, mon, 1), end=_end_of_month(y, mon))
    return None


def _mk_date(y, mo, d, rule, asm) -> _R:
    try:
        return _R("date", rule, start=date(y, mo, d), assumptions=list(asm))
    except ValueError:
        return _R("none", rule, status="UNPARSEABLE", assumptions=["INVALID_CALENDAR_DATE"])


def _month_day(mon, day, year, weekday, ctx, rule) -> _R:
    if year is not None:
        r = _mk_date(year, mon, day, rule, [])
        if r.status == "RESOLVED" and weekday is not None and r.start.weekday() != weekday:
            r.assumptions.append("WEEKDAY_DATE_MISMATCH")
        return r
    return _partial_md(mon, day, weekday, ctx, rule, [])


def _partial_md(mon, day, weekday, ctx, rule, asm) -> _R:
    try:
        date(2000, mon, day)  # validity ignoring year (2000 is a leap year)
    except ValueError:
        return _R("none", rule, status="UNPARSEABLE", assumptions=["INVALID_CALENDAR_DATE"])
    if not ctx.has_anchor:
        return _R("none", rule, status="PARTIAL", candidates=[{"month": mon, "day": day, "year": None}],
                  assumptions=list(asm) + ["YEAR_MISSING"])
    d, note = _infer_year(mon, day, ctx, weekday)
    if d is None:
        return _R("none", rule, status="PARTIAL", candidates=[{"month": mon, "day": day, "year": None}],
                  assumptions=list(asm) + ["YEAR_MISSING"])
    return _R("date", rule, start=d, assumptions=list(asm) + [note])


def _weekday_target(w: int, mode: Optional[str], ctx: _Ctx, cfg) -> _R:
    if not ctx.has_anchor:
        return _no_anchor("weekday")
    today = ctx.ref_date()
    if mode == "this":
        return _R("date", "weekday_this", start=_monday(today) + timedelta(days=w))
    if mode == "next":
        d = _monday(today) + timedelta(days=7 + w)
        asm = ["NEXT_WEEKDAY_ISO_WEEK"]
        alt = today + timedelta(days=(w - today.weekday()) % 7 or 7)
        cands = [{"date": _iso(alt), "reading": "nearest upcoming"}] if alt != d else []
        return _R("date", "weekday_next", start=d, assumptions=asm, candidates=cands)
    if mode == "last":
        return _R("date", "weekday_last", start=_monday(today) - timedelta(days=7) + timedelta(days=w))
    # bare weekday or 'coming/upcoming'
    delta = (w - today.weekday()) % 7
    if delta == 0 and mode is None and cfg["bare_weekday_same_day"] == "ambiguous":
        return _R("date", "weekday_bare", status="AMBIGUOUS", start=None,
                  candidates=[{"date": _iso(today), "reading": "today"}, {"date": _iso(today + timedelta(days=7)), "reading": "next week"}])
    if delta == 0:
        delta = 7
    return _R("date", "weekday_bare" if mode is None else "weekday_coming", start=today + timedelta(days=delta))


def _parse_date_part(s: str, ctx: _Ctx) -> Optional[_R]:
    cfg = ctx.cfg
    r = _parse_absolute(s, ctx)
    if r:
        return r
    s = re.sub(r"'s$", "", s)
    # relative days (+ optional part of day)
    m = re.fullmatch(rf"(today|tonight|tomorrow|yesterday|(?:the )?day after tomorrow|(?:the )?day before yesterday)(?:\s+(?:in the\s+)?({'|'.join(PARTS)}))?", s)
    if m:
        if not ctx.has_anchor:
            return _no_anchor("relative_day")
        offs = {"today": 0, "tonight": 0, "tomorrow": 1, "yesterday": -1}
        word = m[1]
        off = offs.get(word, 2 if "after tomorrow" in word else -2)
        part = "night" if word == "tonight" else m[2]
        return _R("date", "relative_day", start=ctx.ref_date() + timedelta(days=off), part=part)
    m = re.fullmatch(rf"(?:this|that)\s+({'|'.join(PARTS)})", s)
    if m:
        if not ctx.has_anchor:
            return _no_anchor("this_part_of_day")
        return _R("date", "this_part_of_day", start=ctx.ref_date(), part=m[1])
    m = re.fullmatch(rf"(?:(this|next|last|coming|upcoming)\s+)?{_WD}(?:\s+(?:in the\s+)?({'|'.join(PARTS)}))?", s)
    if m:
        res = _weekday_target(WEEKDAYS[m[2]], m[1], ctx, cfg)
        res.part = m[3]
        return res
    m = re.fullmatch(rf"(?:in\s+the\s+|in\s+)?({'|'.join(PARTS)})", s)
    if m:
        return _R("none", "part_of_day_only", status="PARTIAL", part=m[1], assumptions=["DATE_MISSING"])
    # offsets
    m = re.fullmatch(r"(?:in\s+)?(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s+(minute|hour|day|week|month)s?(?:\s+(?:from now|from today|later|ahead|time))?", s)
    if m and (s.startswith("in ") or "from" in s or "later" in s):
        n = _num(m[1])
        if n is None:
            return None
        if not ctx.has_anchor:
            return _no_anchor("offset")
        unit = m[2]
        if unit in ("minute", "hour"):
            dt = ctx.ref + (timedelta(hours=n) if unit == "hour" else timedelta(minutes=n))
            ctx.anchor_used = True
            return _R("datetime", "offset_time", start=dt)
        today = ctx.ref_date()
        d = today + timedelta(days=n) if unit == "day" else today + timedelta(weeks=n) if unit == "week" else _add_months(today, n)
        return _R("date", "offset", start=d)
    # periods
    m = re.fullmatch(r"(later|rest of|latter part of)\s+(?:of\s+)?(?:in\s+)?(?:this|the)\s+(week|month)", s)
    if m:
        if not ctx.has_anchor:
            return _no_anchor("rest_of_period")
        t = ctx.ref_date()
        end = _monday(t) + timedelta(days=6) if m[2] == "week" else _end_of_month(t.year, t.month)
        return _R("range", "rest_of_period", start=t, end=end, assumptions=["RANGE_FROM_REFERENCE_DATE"])
    m = re.fullmatch(r"(this|next|last|coming|upcoming)\s+(week|month|year|weekend)", s)
    if m:
        if not ctx.has_anchor:
            return _no_anchor("period")
        t = ctx.ref_date()
        k = {"this": 0, "next": 1, "coming": 1, "upcoming": 1, "last": -1}[m[1]]
        if m[2] == "week":
            st = _monday(t) + timedelta(weeks=k)
            return _R("week", "period_week", start=st, end=st + timedelta(days=6))
        if m[2] == "weekend":
            sat = _monday(t) + timedelta(weeks=k, days=5)
            return _R("range", "period_weekend", start=sat, end=sat + timedelta(days=1))
        if m[2] == "month":
            first = _add_months(date(t.year, t.month, 1), k)
            return _R("month", "period_month", start=first, end=_end_of_month(first.year, first.month))
        y = t.year + k
        return _R("year", "period_year", start=date(y, 1, 1), end=date(y, 12, 31))
    if re.fullmatch(r"(?:the\s+)?year[- ]end", s):
        if not ctx.has_anchor:
            return _no_anchor("year_end")
        return _R("date", "year_end", start=date(ctx.ref_date().year, 12, 31), assumptions=["END_OF_PERIOD"])
    m = re.fullmatch(r"end of\s+(?:the\s+|this\s+|next\s+)?(week|month|year)", s)
    if m:
        if not ctx.has_anchor:
            return _no_anchor("end_of_period")
        t = ctx.ref_date()
        shift = 1 if " next " in f" {s} " else 0
        if m[1] == "week":
            d = _monday(t) + timedelta(weeks=shift, days=4)
            note = "END_OF_WEEK_IS_FRIDAY"
        elif m[1] == "month":
            f = _add_months(date(t.year, t.month, 1), shift)
            d, note = _end_of_month(f.year, f.month), "END_OF_PERIOD"
        else:
            d, note = date(t.year + shift, 12, 31), "END_OF_PERIOD"
        return _R("date", "end_of_period", start=d, assumptions=[note])
    m = re.fullmatch(r"(?:in\s+)?" + _MON + r"(?:\s+(\d{4}))?", s)
    if m:
        mon = MONTHS[m[1]]
        if m[2]:
            y = int(m[2])
            return _R("month", "month_year", start=date(y, mon, 1), end=_end_of_month(y, mon))
        if not ctx.has_anchor:
            return _R("none", "month_only", status="PARTIAL", candidates=[{"month": mon, "year": None}],
                      assumptions=["YEAR_MISSING"])
        t = ctx.ref_date()
        y = t.year if mon >= t.month else t.year + 1
        return _R("month", "month_only", start=date(y, mon, 1), end=_end_of_month(y, mon), assumptions=["YEAR_INFERRED"])
    m = re.fullmatch(r"(?:in\s+)?(\d{4})", s)
    if m and 1900 <= int(m[1]) <= 2100:
        y = int(m[1])
        return _R("year", "year", start=date(y, 1, 1), end=date(y, 12, 31))
    return None

def _parse_date_list(text: str, ctx: _Ctx) -> Optional[_R]:
    """'Thursday or Friday', 'sat and sun', 'tomorrow, sunday and monday' -> AMBIGUOUS with candidates."""
    parts = [p for p in re.split(r"\s*(?:,\s*(?:and|or)\s+|,\s*|\s+and\s+|\s+or\s+|/)\s*", text) if p]
    if len(parts) < 2:
        return None
    results = []
    for part in parts:
        r = _parse_date_part(part, ctx)
        if r is None or (r.kind != "date" and not r.needs_anchor):
            return None
        results.append(r)
    if any(r.status == "UNRESOLVED_NO_ANCHOR" for r in results):
        return _R("none", "date_list", status="UNRESOLVED_NO_ANCHOR", assumptions=["MULTIPLE_DATES"])
    cands = []
    for r in results:
        if r.status == "RESOLVED":
            cands.append({"date": _iso(r.start)})
        elif r.status == "AMBIGUOUS":
            cands.extend(r.candidates)
        else:
            return None
    return _R("none", "date_list", status="AMBIGUOUS", candidates=cands, assumptions=["MULTIPLE_DATES"])


# --------------------------------------------------------------------------- assembly
def _localize(d: date, t: time, ctx: _Ctx, asm: list[str]):
    naive = datetime.combine(d, t)
    if ctx.tz is None:
        return naive
    aware = naive.replace(tzinfo=ctx.tz)
    if aware.astimezone(_tz.utc).astimezone(ctx.tz).replace(tzinfo=None) != naive:
        asm.append("DST_GAP_ADJUSTED")
    elif aware.replace(fold=1).utcoffset() != aware.utcoffset():
        asm.append("DST_AMBIGUOUS_TIME_FIRST_OCCURRENCE")
    return aware


def _compare_past(tv: TemporalValue, ctx: _Ctx) -> Optional[bool]:
    if ctx.ref is None:
        return None
    end = tv.end or tv.value or tv.start
    if not end:
        return None
    try:
        if "T" in end:
            dt = datetime.fromisoformat(end)
            ref = ctx.ref
            if (dt.tzinfo is None) != (ref.tzinfo is None):
                dt, ref = dt.replace(tzinfo=None), ref.replace(tzinfo=None)
            return dt < ref
        return date.fromisoformat(end) < ctx.ref.date()
    except ValueError:
        return None


def normalize_temporal(raw: str, *, reference_ts=None, timezone: Optional[str] = None,
                       relation_hint: Optional[str] = None, config: Optional[Mapping[str, Any]] = None) -> TemporalValue:
    """Normalise one temporal expression. ``relation_hint`` is carried for provenance only."""
    ctx = _Ctx(reference_ts, timezone, config)
    tv = TemporalValue(raw=raw)
    tv.assumptions.extend(ctx.assumptions)
    if ctx.has_anchor:
        tv.anchor_used = ctx.ref.isoformat()
    s = re.sub(r"\s+", " ", (raw or "").strip().lower()).strip(" .,;:")
    s = s.replace("’", "'")
    if not s:
        tv.rule_id = "empty"
        return tv

    s = re.sub(r"\baft\b", "afternoon", s)
    wm = WITHIN_RE.match(s)
    if wm:
        n_ = _num(wm[1])
        tv.deadline_phrase, tv.rule_id = True, "within_window"
        if not ctx.has_anchor:
            tv.status = "UNRESOLVED_NO_ANCHOR"
            return tv
        t0 = ctx.ref_date()
        end_ = (t0 + timedelta(days=n_) if wm[2] == "day" else t0 + timedelta(weeks=n_) if wm[2] == "week"
                else _add_months(t0, n_) if wm[2] == "month" else t0)
        tv.status, tv.granularity = "RESOLVED", "RANGE"
        tv.start, tv.end = _iso(t0), _iso(end_)
        tv.assumptions += ["WITHIN_WINDOW", "RANGE_FROM_REFERENCE_DATE"] + (["WITHIN_HOURS_DATE_ONLY"] if wm[2] == "hour" else [])
        return _finish(tv, ctx)
    changed = True
    while changed:
        changed = False
        m = DEADLINE_PREFIX.match(s)
        if m:
            tv.deadline_phrase, s, changed = True, s[m.end():], True
            continue
        m = LOOSE_PREFIX.match(s)
        if m:
            s, changed = s[m.end():], True
            continue
        m = MODIFIER_PREFIX.match(s)
        if m:
            tv.assumptions.append(f"MODIFIER_APPROXIMATED:{m[1].lower().rstrip('-')}")
            s, changed = s[m.end():], True
    s = s.strip(" .,;:")
    if DURATION_RE.match(s):
        tv.status, tv.rule_id = "UNPARSEABLE", "duration"
        tv.assumptions.append("DURATION_NOT_A_TIME")
        return tv

    if RECURRING_RE.search(s):
        tv.status, tv.rule_id = "VAGUE", "recurring"
        tv.assumptions.append("RECURRING_UNSUPPORTED")
        return tv
    if EVENT_PREFIX.match(s):
        tv.status, tv.rule_id = "UNRESOLVED_EVENT_CONDITION", "event_condition"
        return tv
    after = AFTER_PREFIX.match(s)
    if after:
        inner = normalize_temporal(s[after.end():], reference_ts=reference_ts, timezone=timezone, config=config)
        if inner.status in ("RESOLVED", "PARTIAL", "AMBIGUOUS", "UNRESOLVED_NO_ANCHOR") and inner.rule_id != "event_condition":
            inner.raw, inner.deadline_phrase = raw, tv.deadline_phrase
            inner.assumptions.append("BOUND_AFTER")
            inner.rule_id = f"after:{inner.rule_id}"
            return inner
        tv.status, tv.rule_id = "UNRESOLVED_EVENT_CONDITION", "event_condition_after"
        return tv
    if VAGUE_RE.match(s):
        tv.status, tv.rule_id = "VAGUE", "vague"
        return tv

    time_part = None
    date_text = s
    whole_time = _parse_time(s, ctx)
    split = None if whole_time is not None else _split_time(s)
    if split:
        date_text, time_text = split
        time_part = _parse_time(time_text, ctx)
        if time_part is None:
            date_text, time_part = s, None
    result: Optional[_R] = None
    if time_part is None and whole_time is not None:
        t, t_end, asm = whole_time
        if "TIME_CONVENTION_APPLIED" in asm and ctx.has_anchor:
            day = ctx.ref_date()
            tv.status, tv.granularity, tv.rule_id = "RESOLVED", "DATETIME", "eod_today"
            dt = _localize(day, t, ctx, tv.assumptions)
            tv.value = tv.start = tv.end = dt.isoformat()
            tv.assumptions += asm + ["DATE_ASSUMED_REFERENCE_DAY"]
            tv.in_past = _compare_past(tv, ctx)
            return _finish(tv, ctx)
        tv.status, tv.granularity, tv.rule_id = "PARTIAL", "TIME_ONLY", "time_only"
        tv.value = t.isoformat(timespec="minutes")
        tv.start, tv.end = tv.value, (t_end.isoformat(timespec="minutes") if t_end else tv.value)
        tv.assumptions += asm + ["DATE_MISSING"]
        return tv
    result = _parse_date_part(date_text, ctx)
    if result is None and time_part is None:
        listed = _parse_date_list(date_text, ctx)
        if listed is not None:
            tv.rule_id = "date_list"
            tv.assumptions += listed.assumptions
            tv.candidates = listed.candidates
            tv.status = listed.status
            tv.granularity = "DATE" if listed.status == "AMBIGUOUS" else None
            return _finish(tv, ctx)
    if result is None:
        if (tv.deadline_phrase or CLAUSE_RE.match(s)) and len(s.split()) >= 3:
            tv.status, tv.rule_id = "UNRESOLVED_EVENT_CONDITION", "event_clause"
            return tv
        tv.status, tv.rule_id = "UNPARSEABLE", "no_rule"
        return tv

    tv.rule_id = result.rule
    tv.assumptions += result.assumptions
    tv.candidates = result.candidates
    tv.part_of_day = result.part
    if result.status in ("UNRESOLVED_NO_ANCHOR", "UNPARSEABLE", "PARTIAL"):
        tv.status = result.status
        if result.part and result.status == "PARTIAL":
            tv.granularity = "PART_OF_DAY"
        if time_part:
            t, t_end, asm = time_part
            tv.assumptions += asm + ["TIME_PARSED_DATE_PENDING"]
            tv.candidates = tv.candidates or [{"time": t.isoformat(timespec="minutes")}]
        if ctx.floating and ctx.has_anchor:
            tv.assumptions.append("TZ_ASSUMED")
        return tv
    if result.status == "AMBIGUOUS":
        tv.status = "AMBIGUOUS"
        tv.granularity = "DATE"
        return _finish(tv, ctx)

    tv.status = "RESOLVED"
    kind = result.kind
    if kind == "datetime":
        dt = result.start
        tv.granularity, tv.value, tv.start, tv.end = "DATETIME", dt.isoformat(), dt.isoformat(), dt.isoformat()
    elif kind == "date":
        d = result.start
        if time_part:
            t, t_end, asm = time_part
            dt = _localize(d, t, ctx, tv.assumptions)
            tv.assumptions += asm
            tv.granularity, tv.value, tv.start = "DATETIME", dt.isoformat(), dt.isoformat()
            tv.end = _localize(d, t_end, ctx, tv.assumptions).isoformat() if t_end else tv.start
        else:
            tv.granularity = "PART_OF_DAY" if result.part else "DATE"
            tv.value = tv.start = tv.end = _iso(d)
    else:
        tv.granularity = {"week": "WEEK", "month": "MONTH", "year": "YEAR", "range": "RANGE"}[kind]
        tv.start, tv.end = _iso(result.start), _iso(result.end)
        if time_part:
            tv.assumptions.append("TIME_IGNORED_FOR_RANGE")
    tv.in_past = _compare_past(tv, ctx)
    return _finish(tv, ctx)


def _finish(tv: TemporalValue, ctx: _Ctx) -> TemporalValue:
    if tv.status == "AMBIGUOUS":
        tv.in_past = None
    if ctx.floating and ctx.anchor_used:
        tv.assumptions.append("TZ_ASSUMED")
    seen: list[str] = []
    for a in tv.assumptions:
        if a not in seen:
            seen.append(a)
    tv.assumptions = seen
    return tv
