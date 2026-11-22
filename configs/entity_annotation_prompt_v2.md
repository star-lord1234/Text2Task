<!-- prompt_version: text2task-entity-v2.0.2 -->

Return one JSON object only:
{"entities":[{"type":"TASK|PERSON|TEMPORAL","text":"exact substring","start":0,"end":1,"negated":false,"ambiguous":false}],"notes":[]}

Annotate only the TARGET EMAIL, never context. Offsets are zero-based half-open
and `text` must equal TARGET_EMAIL[start:end]. Empty entities are valid.

TASK is only a current actionable request, future commitment, prohibition, or
concrete planned action. Exclude historical/completed events, descriptions,
states, attachments being presented, topics, greetings, and advertisements.
Use the smallest complete predicate plus necessary object. Do not make nested
or duplicate TASKs. Preserve negation and modality. Exclude detachable dates,
owners, politeness, and evidence from TASK.

PERSON is an explicit personal name only—never a pronoun, company, product,
generic role, sentence-initial ordinary word, or inferred participant.
TEMPORAL is the exact date/time/duration/relative-time phrase and is separate
from TASK.

The following thirty hard-case lessons were derived only from the corrected
training-split diagnostic audit. They are semantic reference rules, not text to
copy into the output:

1. `was filed` is historical, while `get citation issued` is a TASK.
2. `called me last week` is history, while a current `talk with Chris` request is
   a TASK.
3. `use the spreadsheet to populate the report` is one TASK.
4. `the spreadsheets were emailed` is completed history.
5. `Frank sent this` is history; `help me find it` may be a current TASK.
6. tickets that `were given` are history; planned attendance may be a TASK.
7. `should be submitted` is planned work and may be a TASK.
8. `has just sent you a card` is history; `click the link` is a TASK.
9. sentence-initial `Top` is not a PERSON.
10. `send your address and fax number` is one TASK, not nested duplicates.
11. `I told him` is a speech report, not a TASK.
12. `check it out` and `pass it around` are distinct coordinated TASKs.
13. reported past instructions are not automatically new TASKs.
14. a passive concrete request such as `needs to be set up` may be a TASK.
15. `entered a deal` is completed history.
16. `did not review` is a past fact; `must be reviewed` is a TASK.
17. `has moved the date` is a completed update, not a CREATE TASK.
18. `communications were disrupted` is history; `investigate` is a TASK.
19. appreciation and greetings can legitimately have no TASK.
20. `will remain under Corporate` describes a state, not necessarily work.
21. `do not insert the clause` is a negated TASK.
22. interview scheduling and `reserve this time` can be separate TASKs.
23. `Friday` is TEMPORAL and `on` alone is not an entity.
24. keep `from now until year end` separate from an action TASK.
25. `here is the list` presents information and is not a TASK.
26. `it was due 10/1` may have TEMPORAL but is not a new TASK.
27. `have signed the documents` is history; `send a copy` is a TASK.
28. `my phone is ...` and `the shop will remain closed` are descriptive.
29. `rejected the proposal` is history; `let me know how to proceed` is a TASK.
30. `the curves are attached`, advertisements, disclaimers, and signatures are
    not TASKs.

TARGET EMAIL:
<TARGET_EMAIL>
{{EMAIL_TEXT}}
</TARGET_EMAIL>

Offsets are checked against the source after generation. If uncertain, preserve
the exact source substring and do not guess or normalize its spelling.
