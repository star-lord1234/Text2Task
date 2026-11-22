"""Step 4: lightweight grammatical analysis (dependency-free chunker).

Finds action phrases (verb + object noun phrase) from closed-class words and the action-verb lexicon, using positional evidence for the verb:
sentence/clause start (imperative), after 'please', after 'to', after a modal ('can you clean', 'should evaluate'), or after a subject
('you clean', 'Anushree finishes'). It recovers phrases the neural model missed, completes dangling neural spans ('train the' -> 'train the
model'), and finds roster names used as vocatives or subjects. It never guesses an owner: owners are still resolved by Phase 4."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from src.refine.lexicon import (ACTION_VERBS, AUX, CLAUSE_CUE, CLOSED, DET, GENERIC_VERBS, OBJECT_PRONOUNS, PHRASAL_PARTICLES, POLITE, PREP, PRON,
                                STATE_PARTICIPLE_SUFFIX, STATE_WORDS)

TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*|[^\sA-Za-z0-9]")
TRUE_MODALS = {"can", "could", "will", "would", "shall", "should", "must", "may", "might", "ll"}
MODAL_LIKE = {"can", "could", "will", "would", "shall", "should", "must", "may", "might", "ll", "need", "needs", "needed", "have", "has", "going"}
MAX_PHRASE_TOKENS = 9


@dataclass
class Tok:
    text: str
    low: str
    start: int
    end: int

    @property
    def is_word(self) -> bool:
        return bool(re.match(r"[A-Za-z0-9]", self.text))


def tokenize(text: str, a: int = 0, b: Optional[int] = None) -> list[Tok]:
    b = len(text) if b is None else b
    return [Tok(m.group(0), m.group(0).lower().replace("’", "'"), m.start(), m.end()) for m in TOKEN.finditer(text, a, b)]


def lemma(w: str) -> Optional[str]:
    """Base form if `w` is (an inflection of) a lexicon action verb, else None."""
    w = w.lower()
    if w in ACTION_VERBS:
        return w
    cands = []
    for suf, rep in (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"), ("ing", ""), ("ing", "e"), ("d", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            cands.append(w[:-len(suf)] + rep)
    if len(w) > 4 and w[-1] == w[-2] and w.endswith(("ed", "ing")) is False:
        pass
    for c in list(cands):                                          # doubled consonant: "stopped" -> "stop"
        if len(c) > 2 and c[-1] == c[-2]:
            cands.append(c[:-1])
    return next((c for c in cands if c in ACTION_VERBS), None)


@dataclass
class Phrase:
    start: int
    end: int
    verb: str
    evidence: str
    text: str


def _inside(p: int, protected: Sequence[tuple[int, int]]) -> bool:
    return any(a <= p < b for a, b in protected)


def find_action_phrases(text: str, a: int = 0, b: Optional[int] = None, *, protected: Sequence[tuple[int, int]] = (),
                        names: Iterable[str] = ()) -> list[Phrase]:
    """Action phrases in text[a:b]. `protected` are character ranges (PERSON/TEMPORAL entities) a phrase must stop at."""
    toks = tokenize(text, max(0, a - 60), b)          # a little left context, so the word before the range still counts as evidence
    names = {n.lower() for n in names}
    out: list[Phrase] = []
    i = 0
    while i < len(toks):
        if toks[i].start < a:
            i += 1
            continue
        t = toks[i]
        base = lemma(t.low) if t.is_word else None
        if base is None or _inside(t.start, protected):
            i += 1
            continue
        prev = toks[i - 1] if i else None
        prev2 = toks[i - 2] if i > 1 else None
        evidence = None
        is_base = t.low == base
        third_person = prev is not None and (prev.low in names or prev.low in {"someone", "anyone", "somebody", "anybody"})
        if prev is None or not prev.is_word and prev.text in ",;:.!?-" or (prev and prev.low in POLITE):
            evidence = "imperative/clause-start" if is_base else None                     # an imperative is a base form ("Finished the report" is a report)
        elif prev.low in CLAUSE_CUE:
            if is_base:
                evidence = "imperative/clause-start"
            elif t.low.endswith("ing") and prev.low in {"before", "after", "until", "once", "when", "while"}:
                evidence = "gerund after clause cue"                                       # "before sending it to finance"
        elif prev.low == "to" and is_base:
            evidence = "infinitive"
        elif (prev.low in TRUE_MODALS or (prev.low == "you" and prev2 and prev2.low in TRUE_MODALS)) and is_base:
            evidence = "after modal"                                                       # not be/have/get: "was cancelled" is a passive
        elif prev.low in {"me", "us"} and prev2 and prev2.low == "let" and is_base:
            evidence = "after let"
        elif prev.low in PRON or prev.low in names:
            if is_base and prev.low in {"you", "we", "i", "they", "someone", "anyone", "somebody", "anybody"} | names:
                evidence = "after subject"
            elif third_person and t.low in {base + "s", base + "es"}:
                evidence = "after subject"                                                 # 3rd-person present ("Anushree finishes ...")
        if evidence is None:
            i += 1
            continue
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if evidence in ("imperative/clause-start", "gerund after clause cue") and nxt is not None and nxt.low in AUX:      # "Release is delayed": a noun, not an imperative
            i += 1
            continue
        # phrase extent
        j = i + 1
        if nxt is not None and nxt.low in PHRASAL_PARTICLES and not _inside(nxt.start, protected) and base in {"set", "back", "follow", "sign", "wrap", "hand", "look", "take", "write", "clean", "send", "check", "pick", "drop", "sort", "tidy", "clear", "start", "kick", "open", "close", "fill", "pull", "run"}:
            j += 1
        k = j
        while k < len(toks) and k - i < MAX_PHRASE_TOKENS:
            u = toks[k]
            if not u.is_word and u.text not in "'-&/":
                break
            if u.low in CLAUSE_CUE or u.low in AUX or _inside(u.start, protected):
                break
            if u.low in {"by", "on", "at", "for", "until", "till", "before", "after", "from"} and k + 1 < len(toks) and _inside(toks[k + 1].start, protected):
                break
            k += 1
        if evidence in ("imperative/clause-start", "gerund after clause cue") and k < len(toks) and toks[k].low in AUX and toks[k].low not in {"can", "could", "will", "would", "should", "must"}:
            i += 1                                                              # 'Release notes are due': the phrase is a subject noun phrase
            continue
        end_i = k
        while end_i > j and toks[end_i - 1].low in (DET | PREP | POLITE | CLAUSE_CUE) and toks[end_i - 1].low not in OBJECT_PRONOUNS:
            end_i -= 1                                                          # no dangling 'the'/'to' at the end
        body = toks[j:end_i]
        # a bare verb needs an object unless it is the entire clause; generic commitments are acknowledgements, not tasks
        rest = [x.low for x in body if x.is_word]
        if base in GENERIC_VERBS and (not rest or set(rest) <= OBJECT_PRONOUNS | {"care", "of", "over", "it"}):
            i = max(i + 1, end_i)
            continue
        if not rest and (nxt is not None and nxt.is_word and nxt.low not in CLOSED):
            i += 1
            continue
        s, e = t.start, toks[end_i - 1].end
        out.append(Phrase(s, e, base, evidence, text[s:e]))
        i = max(i + 1, end_i)
    return out


def is_state_clause(clause: str) -> bool:
    """'the dataset is cleaned', 'Anushree has collected the responses', 'it is ready': reports a state, so it refers to existing work."""
    low = [w.lower() for w in TOKEN.findall(clause) if re.match(r"\w", w)]
    for i, w in enumerate(low):
        if w in {"is", "are", "was", "were", "be", "been", "gets", "get", "got", "has", "have", "had", "gets"}:
            for x in low[i + 1:i + 3]:
                if x in STATE_WORDS or (len(x) > 3 and x.endswith(STATE_PARTICIPLE_SUFFIX) and x not in {"need", "seed", "speed", "indeed"}):
                    return True
    return False


def has_action(clause: str, names: Iterable[str] = ()) -> bool:
    return bool(find_action_phrases(clause, names=names))


def roster_mentions(text: str, roster: dict[str, str], taken: Sequence[tuple[int, int]]) -> list[tuple[int, int, str]]:
    """Names from the participant roster used as a vocative ('Bianca,') or as a subject ('Anushree will/should/has ...') that no entity covers.
    Returns (start, end, participant_id)."""
    out = []
    for m in re.finditer(r"\b([A-Za-z][A-Za-z\-']+)\b", text):
        pid = roster.get(m.group(1).lower())
        if not pid or _inside(m.start(), taken):
            continue
        after = text[m.end():m.end() + 24]
        nxt = re.match(r"\s*([A-Za-z']+)", after)
        before = text[:m.start()].rstrip()
        vocative = after.lstrip().startswith(",") and (not before or before[-1] in ".!?;:," or before.lower().endswith(("thanks", "hi", "hey", "dear", "please")))
        at_start = not before or before[-1] in ".!?;:,"
        follows_modal = bool(nxt) and nxt.group(1).lower() in AUX | MODAL_LIKE
        # 'Anushree should evaluate' is a subject wherever it sits; 'Anushree finishes' only when it opens its own clause (not inside 'once ... finishes')
        subject = bool(nxt) and ((follows_modal and (at_start or before.split()[-1].lower() in CLAUSE_CUE | {"and", "so"})) or (at_start and lemma(nxt.group(1)) is not None))
        if vocative or subject:
            out.append((m.start(), m.end(), pid))
    return out


def has_verb(text: str) -> bool:
    return any(lemma(w) for w in re.findall(r"[A-Za-z']+", text))
