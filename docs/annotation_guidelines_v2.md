# Text2Task annotation guidelines v2.0

## Scope and provenance

Version 2 tightens the semantic definition of TASK after the SILVER-v1 audit.
It uses the unchanged `text2task_schema_v1.json` machine contract so existing
validators remain applicable. A v2 annotation is still SILVER unless an actual
identified human independently reviews it. LLM output, deterministic repair,
and this diagnostic review never create GOLD data.

The thirty audited examples used to develop these rules all come from the
original MailEx training split. Development and test records must never be used
as prompt demonstrations or prompt-tuning feedback. Test annotations remain
untouched.

## TASK decision test

Annotate TASK only when all three questions answer yes:

1. Is there an action rather than a fact, topic, object, or state?
2. Does the email request, commit to, prohibit, cancel, update, or concretely
   plan that action at the email's discourse time?
3. Can the smallest complete actionable predicate and object be selected as an
   exact span?

If any answer is no, do not force TASK. Empty-task emails are valid negative
examples and must be preserved.

Completed history is not a newly actionable task. It may represent a COMPLETE
or CANCEL update only when the thread provides supported identity to a specific
existing task. Otherwise use EVENT only if the occurrence is necessary to
understand another task; otherwise omit it.

## Boundaries and overlaps

TASK includes the predicate, explicit negation/modality that changes meaning,
and the necessary object/complement. Exclude greetings, named owners, detachable
dates/deadlines, evidence clauses, and politeness. Never create a short TASK
inside a longer TASK for the same action merely because both are grammatical.

For the three-class token model, overlaps are resolved deterministically:

1. retain TASK over TEMPORAL only when the temporal words are grammatically
   inseparable; normally TEMPORAL is trimmed out of TASK;
2. retain PERSON as its exact named span and trim TASK subjects/owners;
3. for same-type overlap, retain the smallest complete actionable span;
4. if trimming would destroy meaning, quarantine the record from the
   single-layer model rather than overwrite a label.

The character-span annotation format may still preserve justified overlaps for
future models. The single-layer training view records every resolution.

## Modality, negation, and uncertainty

Keep `not`, `do not`, `must not`, `might`, `may`, `should`, `would`, `plan`,
`propose`, and `try` when they materially change the action. A prohibition such
as “do not send” is a pending negated TASK, not automatically a cancellation.
A tentative suggestion can be TASK when it communicates planned/requested work;
set `ambiguous=true` where commitment is unclear. A hypothetical condition with
no intended action is not TASK.

## Other entities

- PERSON: explicit personal name only. No pronouns, generic roles, companies,
  products, sentence-initial capitalization, phone numbers, or inferred people.
- GROUP: explicit named team/committee/collective only. Generic “team” is not
  sufficient unless locally established as a specific name.
- TEMPORAL: exact complete date, time, duration, relative time, or schedule
  phrase. Keep it separate from TASK whenever possible.
- ARTIFACT: explicit concrete document, file, report, form, attachment, deck, or
  deliverable. Do not turn abstract information into an artifact.
- EVENT: only an occurrence/state relevant to a task or real prerequisite.

Never fabricate an entity to make a relation possible. Pronoun-only ownership
remains unresolved. Missing dates and owners remain explicitly missing.

## Relations

DUE_ON means completion is required by a boundary. SCHEDULED_ON means intended
execution time. DEPENDS_ON requires a necessary input, authorization, or true
contingency; “after,” “before,” “once,” and “when” are not sufficient alone.
Every positive edge needs exact evidence. REFERS_TO remains deferred and NONE is
only a candidate-pair label.

## Thirty difficult cases

1. “The lawsuit was filed at 11:06.” — historical EVENT, not TASK.
2. “Get citation issued.” — TASK because it is necessary planned work.
3. “Do not mention the lawsuit.” — negated TASK; retain “do not.”
4. “She called me last week.” — past event; TEMPORAL may remain, no TASK.
5. “Talk with Chris in settlements.” — current request TASK; Chris is PERSON.
6. “Use the spreadsheet to populate the report.” — one TASK; spreadsheet/report
   may separately be ARTIFACT.
7. “The spreadsheets were emailed.” — historical completion unless linked to an
   existing task; not automatically TASK.
8. “Frank sent this to me.” — history; Frank remains PERSON.
9. “Alice can help me find it.” — request/planned TASK when the context genuinely
   asks for help; do not annotate “can” alone.
10. “The kids were given tickets.” — completed history, not TASK.
11. “We are going to the game Friday.” — planned activity can be TASK;
    “Friday” is separate TEMPORAL.
12. “The heading should be Receipt/Delivery Points.” — proposed edit TASK, not a
    confirmed completed update.
13. “The service sent you a card.” — automated historical event, not TASK.
14. “Click the pickup link.” — explicit instruction TASK.
15. “Top analysts...” — “Top” is not a personal name.
16. “Send your address and fax number.” — one complete TASK, not two nested copies.
17. “I told him...” — speech report, not TASK.
18. “Check it out and pass it around.” — two coordinated TASKs when each can be
    acted on independently.
19. “They were instructed not to sell.” — reported historical directive, not a
    new task assigned by this email.
20. “A rate-server handle needs to be set up.” — concrete requested work may be
    TASK even in passive voice.
21. “The trader entered a deal.” — completed event, not TASK.
22. “The board did not review it.” — past negated fact, not a prohibition TASK.
23. “The budget must be reviewed at the next meeting.” — TASK plus separate
    TEMPORAL.
24. “He has moved the date to 6/27.” — completed update, not CREATE TASK; 6/27 is
    TEMPORAL.
25. “Communications were disrupted yesterday.” — historical EVENT/state, not TASK.
26. “Investigate how to keep messages flowing.” — actionable TASK.
27. “Do not insert the clause.” — negated TASK; not necessarily CANCEL.
28. “The shop will remain closed.” — future state, not assigned work.
29. “The curves are attached.” — descriptive document presentation, not TASK.
30. “Let me know how to proceed.” — actionable information request TASK, with
    unresolved/implicit owner rather than an invented PERSON.

## Quality-control gates

Every output must pass the JSON/schema validator, exact-offset checks, endpoint
type checks, and the v2 semantic-quality checker. Severe semantic warnings are
quarantined from model training. The checker never silently repairs meaning.
Corrections are stored beside the original SILVER-v1 annotation, with model,
prompt version, timestamp, source ID, and validation history.

A new deterministic sample of thirty training emails must be reviewed after the
v2 run. Report major/minor/acceptable counts and compare them with the v1 audit.
This is an AI-assisted quality estimate, not human GOLD adjudication.
