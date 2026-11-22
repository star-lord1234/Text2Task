"""Closed-class word lists and a small action-verb lexicon for the dependency-free chunker.

Investigated alternatives (step 4): spaCy and NLTK are not installed in this environment and adding either needs a model/corpus download, so
the chunker uses closed-class function words (a small, stable, enumerable set) plus an explicit action-verb lexicon. Verbs outside the
lexicon are still accepted when grammar gives positional evidence (directly after a modal, 'please', 'to', or a vocative).
Nothing here is learned from, or tuned on, any evaluation text."""

from __future__ import annotations

DET = set("a an the this that these those my your our their his her its some any each every all another no".split())
PREP = set("to of in on at by for with from about into onto over under between through during before after until till as per via within without against among".split())
PRON = set("i you we he she it they me us him them someone anyone somebody anybody everyone everybody nobody who whom whose what which myself yourself".split())
AUX = set("can could will would shall should must may might do does did is are am was were be been being have has had get gets got can't cannot won't couldn't shouldn't wouldn't isn't aren't wasn't don't doesn't didn't".split())
CLAUSE_CUE = set("and or but then once after before until till when whenever if because so since while unless as".split())
POLITE = set("please kindly just also still now maybe perhaps actually really definitely first finally next only".split())
CLOSED = DET | PREP | PRON | AUX | CLAUSE_CUE | POLITE | set("need needs needed want wants wanted let going supposed".split()) | {"not", "n't", "t", "s", "ll", "d", "re", "ve", "m", "ok", "okay", "yes", "no", "thanks", "thank", "sure"}

# base-form action verbs that start a task phrase ("review the slides"). Deliberately excludes very generic verbs (get, make, go, see, let, give).
ACTION_VERBS = set("""
send review prepare write draft update create fix clean train deploy schedule book call email check finish complete submit upload download test
evaluate analyze analyse collect export import build run set back follow sign wrap hand look take read edit proofread revise rewrite design
implement develop code ship release publish post share forward reply respond confirm approve reject verify validate compile compute calculate
plan organize organise arrange order buy pay renew cancel reschedule move push merge rebase refactor document summarize summarise present
demo record register apply file print scan translate install configure migrate backup restore monitor investigate research find fetch pull
gather label annotate tag assign notify remind ping contact meet discuss decide resolve close reopen open start begin launch kick finalize
finalise tidy sort rename delete remove archive prepare brief interview hire onboard train coach mentor pick drop clear reserve decorate cook
bake clean vacuum water feed walk drive pack unpack mail fax scan sketch model tune benchmark profile debug log trace patch upgrade
""".split())
PHRASAL_PARTICLES = {"up", "off", "out", "over", "in", "into", "on", "down", "away", "through"}
# verbs that are only a commitment ("take care of it", "handle it", "do it"): an acknowledgement, never a new task phrase
GENERIC_VERBS = {"do", "handle", "take", "deal"}
OBJECT_PRONOUNS = {"it", "this", "that", "them", "these", "those"}
# participles/states that report completion of a referent ("the dataset is cleaned")
STATE_PARTICIPLE_SUFFIX = ("ed", "en")
STATE_WORDS = {"done", "ready", "complete", "completed", "finished", "approved", "signed", "ok", "okay", "live", "set"}
# a prerequisite clause built on one of these ("once Anushree finishes the dataset") reports progress on EXISTING work, so it is a reference, not a new task
COMPLETION_VERBS = {"finish", "complete", "wrap", "conclude", "deliver", "submit", "approve", "sign", "merge", "ship", "release", "publish"}
