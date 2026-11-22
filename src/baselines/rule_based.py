"""Rule-based baseline (experiment E1): regex/lexicon extraction of TASK, PERSON, TEMPORAL spans.

No learning and no MailEx labels are used. Rules were designed by inspecting TRAIN-split
reference spans only. ``extract_spans`` returns character spans ``(type, start, end)``.
"""

from __future__ import annotations

import re
from typing import Sequence

Span = tuple[str, int, int]

# ---------------------------------------------------------------- TEMPORAL
_WEEKDAY = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?"
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DAYPART = r"(?:morning|afternoon|evening|night|noon|midnight|weekend)"
_UNIT = r"(?:day|week|month|year|quarter|hour|minute)s?"
_TIME = r"\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)|\d{1,2}:\d{2}"
_TEMPORAL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    rf"(?:{_WEEKDAY}),?\s+(?:{_MONTH})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?"   # Thursday, March 23
    rf"|(?:{_MONTH})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?"                     # March 23, 2001
    rf"|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?"                                               # 11/26/2001
    rf"|(?:next|last|this|the following|the coming)\s+(?:{_WEEKDAY}|{_UNIT}|{_DAYPART}|{_MONTH})"
    rf"|(?:end|close|beginning|middle)\s+of\s+(?:the\s+)?(?:day|week|month|year|business)"
    rf"|this\s+{_DAYPART}"
    rf"|{_TIME}"
    rf"|(?:today|tomorrow|tonight|yesterday|asap|eod|cob|{_WEEKDAY}|{_DAYPART})"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# 'may' and 'sat'/'sun'/'mar' etc. are ambiguous; require a following digit for bare month words handled above.
_AMBIGUOUS_BARE = {"may", "sat", "sun", "mar", "wed", "mon"}

# ---------------------------------------------------------------- PERSON
_NAME_TOKEN = r"[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*"
_NAME = rf"{_NAME_TOKEN}(?:\s+(?:[A-Z]\.\s+)?{_NAME_TOKEN}){{0,2}}"
_NOT_NAMES = {
    "i", "you", "we", "he", "she", "they", "it", "the", "this", "that", "these", "those", "there", "here", "thanks",
    "thank", "please", "hi", "hello", "dear", "regards", "best", "sincerely", "let", "if", "and", "but", "also",
    "enron", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february",
    "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "today",
    "tomorrow", "yes", "no", "ok", "okay", "attached", "see", "sent", "from", "subject", "fyi", "note", "also",
    "team", "group", "company", "corp", "inc", "ltd", "desk", "department", "all", "everyone", "gentlemen",
    "sirs", "mr", "mrs", "ms", "dr", "do", "does", "did", "can", "could", "would", "will", "should", "what", "when",
    "where", "who", "why", "how", "any", "some", "our", "your", "my", "his", "her", "their", "his", "as", "at", "in",
    "on", "for", "to", "of", "with", "by", "is", "are", "was", "were", "be", "have", "has", "had", "not", "so", "now",
    "then", "just", "very", "well", "thank", "good", "great", "new", "one", "two", "three", "first", "last", "next",
}
_SALUTATION_RE = re.compile(rf"(?:^|\n)\s*(?:(?:hi|hello|dear|hey)\s+)?(?P<n>{_NAME_TOKEN})\s*[,:\-]", re.IGNORECASE)
_CUE_NAME_RE = re.compile(
    rf"\b(?:ask|tell|call|contact|cc|thanks|thank|hi|hello|dear|meet|attn|notify|with)\s+"
    rf"(?P<n>{_NAME_TOKEN}(?:\s+{_NAME_TOKEN})?)(?![A-Za-z])"
)

# ---------------------------------------------------------------- TASK
_IMPERATIVES = (
    "send forward review check confirm advise let call contact provide prepare update complete finish submit approve "
    "sign schedule arrange ensure make give get use help pass keep go try ask tell remember note find remove add "
    "change fix set discuss draft file email fax print attach include verify respond reply read look move run "
    "cancel book order pay take bring share post upload download notify inform copy investigate resolve coordinate "
    "forward place return process review revise enter explain clarify release publish prepare plan consider "
    "double-check recheck re-check follow circulate distribute hold stop do start".split()
)
_VERB = r"(?:" + "|".join(sorted(map(re.escape, _IMPERATIVES), key=len, reverse=True)) + r")"
_END = r"[^.!?;\n]*"
_TASK_PATTERNS = [
    # polite request: please/pls/kindly + anything
    re.compile(rf"(?:^|(?<=[.!?;:\n,\s]))(?P<t>(?:please|pls\.?|kindly)\s+\w+{_END})", re.IGNORECASE),
    # question request: can/could/would/will you (please) VERB ... -> span from verb
    re.compile(rf"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?P<t>\w+{_END})", re.IGNORECASE),
    # let me know
    re.compile(rf"(?P<t>\blet\s+(?:me|us)\s+know{_END})", re.IGNORECASE),
    # clause-initial imperative
    re.compile(rf"(?:^|(?<=[.!?;:\n]\s)|(?<=[.!?;:\n]))\s*(?P<t>{_VERB}\b{_END})", re.IGNORECASE),
    # first-person commitments / obligations
    re.compile(
        rf"\b(?:I|we)\s*(?:'ll|\s+will|\s+shall|\s+am\s+going\s+to|\s+are\s+going\s+to|\s+plan\s+to|\s+need\s+to|\s+have\s+to|\s+must|\s+should)\s+"
        rf"(?!be\b|have\b|not\b)(?P<t>(?:'ll|will|shall|going to|plan to|need to|have to|must|should)?\s*\w+{_END})",
        re.IGNORECASE,
    ),
    # bare future/commitment: will/'ll + verb (not 'will be', 'will have')
    re.compile(rf"(?P<t>\b(?:will|'ll)\s+(?!be\b|have\b|not\b|also be\b|probably\b)\w+{_END})", re.IGNORECASE),
]
_MAX_TASK_WORDS = 14
_MIN_TASK_WORDS = 2
_TRAIL_PREP = re.compile(r"\s+(?:by|on|before|until|at|after|for|in|the|a|an|to|and|or)$", re.IGNORECASE)


def _temporal_spans(text: str) -> list[Span]:
    spans = []
    for m in _TEMPORAL_RE.finditer(text):
        raw = m.group(0)
        if raw.lower() in _AMBIGUOUS_BARE and raw[0].islower():
            continue
        spans.append(("TEMPORAL", m.start(), m.end()))
    return spans


def _person_spans(text: str) -> list[Span]:
    spans: dict[tuple[int, int], Span] = {}

    def accept(name: str) -> bool:
        words = name.split()
        return all(w.lower().strip(".'-") not in _NOT_NAMES for w in words) and not any(
            w.isupper() and len(w) > 1 for w in words
        )

    for m in _SALUTATION_RE.finditer(text):
        s, e = m.span("n")
        if m.group("n")[0].isupper() and accept(m.group("n")):
            spans[(s, e)] = ("PERSON", s, e)
    for m in _CUE_NAME_RE.finditer(text):
        s, e = m.span("n")
        if accept(m.group("n")):
            spans[(s, e)] = ("PERSON", s, e)
    return sorted(spans.values(), key=lambda x: x[1])


def _task_spans(text: str) -> list[Span]:
    found: dict[int, int] = {}
    for pattern in _TASK_PATTERNS:
        for m in pattern.finditer(text):
            s, e = m.span("t")
            raw = text[s:e]
            words = raw.split()
            if len(words) > _MAX_TASK_WORDS:
                cut = len(" ".join(words[:_MAX_TASK_WORDS]))
                e = s + cut
            span_text = text[s:e].rstrip(" ,:-)")
            if len(span_text.split()) < _MIN_TASK_WORDS:
                continue
            e = s + len(span_text)
            if s not in found or e > found[s]:
                found[s] = e
    # drop spans nested in / overlapping a longer span that starts earlier
    ordered = sorted(found.items())
    result: list[Span] = []
    last_end = -1
    for s, e in ordered:
        if s < last_end:
            continue
        result.append(("TASK", s, e))
        last_end = e
    return result


def extract_spans(text: str) -> list[Span]:
    """Return non-overlapping (type, start, end) spans using the single-layer precedence of the dataset."""
    temporal = _temporal_spans(text)
    person = _person_spans(text)
    tasks: list[Span] = []
    for _, s, e in _task_spans(text):
        # cut a TASK before the first TEMPORAL expression it contains (references keep dates separate)
        inside = [t for t in temporal if t[1] < e and s < t[2]]
        if inside:
            e = min(t[1] for t in inside)
            trimmed = _TRAIL_PREP.sub("", text[s:e].rstrip(" ,:-"))
            e = s + len(trimmed)
        if len(text[s:e].split()) >= _MIN_TASK_WORDS:
            tasks.append(("TASK", s, e))
    # PERSON inside a TASK stays part of the TASK, except salutations before it
    persons = [p for p in person if not any(t[1] <= p[1] and p[2] <= t[2] for t in tasks)]
    # remove TEMPORAL that falls inside a PERSON/TASK it cannot split (keep TEMPORAL; TASK was cut)
    spans: list[Span] = []
    for group in (temporal, persons, tasks):
        for sp in group:
            if not any(sp[1] < o[2] and o[1] < sp[2] for o in spans):
                spans.append(sp)
    return sorted(spans, key=lambda x: (x[1], x[2]))


def spans_to_bio(offsets: Sequence[Sequence[int]], spans: Sequence[Span]) -> list[str]:
    """Label tokens (given as character offsets) with BIO tags for the character spans."""
    labels = ["O"] * len(offsets)
    for kind, s, e in spans:
        first = True
        for i, (a, b) in enumerate(offsets):
            if a < e and b > s and b > a:
                labels[i] = ("B-" if first else "I-") + kind
                first = False
    return labels
