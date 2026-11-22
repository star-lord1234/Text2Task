# Phase 4 Plan — Temporal Normalization, Identity Resolution and Uncertainty

**Status:** Draft, awaiting approval. Nothing in this plan has been implemented.
**Source:** `remaining_phases.md` §5, checked against the current repo and the Phase 3 results (`results/relation_extraction/RESULTS.md`).
**Goal:** Turn the extractor's raw output (entity spans plus typed relations) into **actionable task-candidate records**. Dates are normalised only when evidence supports it, assignees are mapped to workspace participants only when unambiguous, and every unresolved field survives into the output with a reason and a clarification question. This stage is deterministic. It trains no new model and needs no GOLD data.

---

## 1. What the repo check found

| Finding | Evidence | Consequence for the plan |
|---|---|---|
| **No record in the corpus has a message timestamp.** `timestamp` is `None` in 0 of 600 `data/final` records, and also in `data/unified` and `data/cleaned`. | direct count | Relative expressions ("Friday", "tomorrow", "next week") cannot be resolved on corpus data. The code must support an explicit `reference_ts` argument for chat messages and report `UNRESOLVED_NO_ANCHOR` otherwise. It must never fall back to the machine date, as `remaining_phases.md` requires. |
| The corpus TEMPORAL spans are mostly relative or vague. Top spans in train: today (30), tomorrow (18), friday (10), next week (9), afternoon (7), yesterday (7), thursday (6), morning (6), and "1:30", "in december" and "on friday" appear 2 times each. | train annotations | The grammar must cover weekday names, relative days, parts of the day, bare times, month-only values and vague terms. Many of these correctly end up *unresolved* or *partial*. |
| **`dateparser` is not installed** and the venv has no `pip`. `python-dateutil` and `zoneinfo` are available. | environment check | Use a small, explicit rule grammar (testable, with no silent guessing) plus `dateutil` for absolute formats. `dateparser` becomes an optional adapter later, **not** a dependency of this phase. |
| Sender and recipient fields are noisy. Senders look like `K. Bass [mailto:daphneco64@alltel.net]`, and recipients are name tokens like `['Bass', 'Eric']`. The workspace (Phase 7) will supply clean participant records. | sample record | Build the resolver against a clean `Participant` registry. Add a clearly labelled, low-trust helper that derives a registry from MailEx fields, for corpus experiments only. |
| PERSON spans in the data include non-individuals ("all", "Enron", "DPC"). The current model has no GROUP type. | train PERSON counts | Collective words resolve to `UNSUPPORTED_GROUP` and are routed to review, never to a participant. |
| Phase 3 behaviour that this phase has to handle: (1) DUE_ON vs SCHEDULED_ON confusion ("by Friday" was predicted SCHEDULED_ON at 0.97). (2) Relation scores are uncalibrated softmax values. (3) Neural and rule linkers disagree on many pairs. | `RESULTS.md` | Add a cue-based **relation/label conflict check**, and a **neural–rule disagreement** flag. Calibrate abstention thresholds on validation (SILVER) data only, and label the results provisional. |

---

## 2. Decisions to confirm before implementation

1. **Parser approach.** I recommend a purpose-built rule grammar plus `dateutil` (no new dependency). The alternative is installing `dateparser` yourself, which has broader coverage but implicit guessing that I would have to constrain. *Default: rule grammar.*
2. **Workspace timezone.** Need a default IANA zone for naive timestamps. *Default: none. Naive timestamps produce floating (timezone-less) values flagged `TZ_ASSUMED`; the app supplies a zone per workspace.*
3. **End-of-day convention.** "EOD" / "COB" / "end of day" need a clock time. *Default: 17:00 in the workspace zone, flagged `TIME_CONVENTION_APPLIED`, and configurable.*
4. **Bare weekday policy.** "Friday" on a Friday is ambiguous (today or next week). *Default: choose the next occurrence strictly after the reference date, and when the reference date is itself that weekday, return `AMBIGUOUS` with both candidates.*
5. **Single-owner MVP.** Multiple ASSIGNED_TO links on one task produce a `MULTIPLE_ASSIGNEES` flag with owner = null, not a silently chosen owner. *Default: yes, as `remaining_phases.md` says all work need not have one owner.*
6. **Review default.** Every flag at `warn` severity or higher sets `review_required = true`. Confidence-based auto-accept is not enabled. *Default: review mode, per the roadmap.*

---

## 3. Data contracts (Step 1)

New `src/pipeline/contracts.py` (plain dataclasses, JSON-serialisable, `schema_version` field).

- **`MessageEnvelope`**: `message_id`, `text`, `sender_id`, `recipient_ids`, `timestamp` (ISO string or null), `timezone` (IANA or null), `thread_id`.
- **`Participant`**: `id`, `display_name`, `aliases[]`, `emails[]`.
- **`TemporalValue`**: `raw`, `status` (`RESOLVED` | `PARTIAL` | `AMBIGUOUS` | `UNRESOLVED_NO_ANCHOR` | `UNRESOLVED_EVENT_CONDITION` | `VAGUE` | `UNPARSEABLE`), `granularity` (`DATE` | `DATETIME` | `TIME_ONLY` | `PART_OF_DAY` | `WEEK` | `MONTH` | `RANGE`), `start`, `end`, `value`, `candidates[]`, `anchor_used`, `assumptions[]`, `rule_id`.
- **`AssigneeResolution`**: `raw`, `status` (`RESOLVED` | `RESOLVED_SENDER` | `RESOLVED_RECIPIENT` | `AMBIGUOUS` | `UNKNOWN_PERSON` | `UNSUPPORTED_GROUP` | `UNASSIGNED`), `participant_id`, `candidates[]`, `basis`.
- **`Flag`**: `code`, `severity` (`info` | `warn` | `block`), `field`, `message`, `question`, `evidence`.
- **`TaskCandidate`**: `candidate_id`, `message_id`, `title`, `task_span`, `assignee: AssigneeResolution`, `due: TemporalValue | null`, `scheduled: TemporalValue | null`, `dependencies[]` (rule-path only, labelled), `flags[]`, `review_required`, `provenance` (model versions, rule IDs, `neural`/`rule`/`both`), `evidence_text`.

`due` and `scheduled` are always separate fields. An unresolved field keeps its raw text and status, and is never dropped.

---

## 4. Steps

### Step 2 — Temporal normalisation (`src/temporal/normalize.py`)

`normalize_temporal(raw, *, reference_ts, timezone, relation_hint=None, config) -> TemporalValue`. Rule IDs are recorded for every output.

- **Absolute:** ISO dates, `March 23, 2001`, `Nov. 15`, `23-NOV-2001`, `9/20`, ranges ("Oct. 29 - Nov. 2"). Fully specified dates resolve without an anchor. Missing year → `PARTIAL`. With an anchor, the year is inferred as the nearest upcoming occurrence and flagged `YEAR_INFERRED`.
- **Relative day:** today, tomorrow, yesterday, tonight, "day after tomorrow". These need an anchor, otherwise `UNRESOLVED_NO_ANCHOR`.
- **Weekday:** `Friday`, `on Monday`, `this Friday`, `next Monday`, `last Tuesday`. The bare-weekday policy is decision 4. "This/next" semantics are fixed in the code and tested, with the ambiguity documented.
- **Time:** `at 10`, `3:30 pm`, `noon`, `midnight`, `10am-11am`. A time-only value is `TIME_ONLY` with no date. It combines with a date from an adjacent TEMPORAL span only when both belong to the same task and relation.
- **Periods:** `next week`, `this weekend`, `later this week`, `in December`, `in 3 days`, `end of the month`. These give week/month ranges or offsets and a `WEEK`/`MONTH` granularity. They never get invented specific days.
- **Parts of day:** morning, afternoon, evening, night. These resolve to the date plus a `PART_OF_DAY` marker, with no invented clock time.
- **Event conditions:** "after approval", "once the draft is done", "as soon as we know the exact date" → `UNRESOLVED_EVENT_CONDITION`. They link to a prerequisite only if the dependency path (Phase 6) supplies one.
- **Vague:** soon, asap, shortly, eventually, "in the near future" → `VAGUE`.
- **Timezone:** use `zoneinfo`. A timestamp without a zone and no workspace default gives floating values flagged `TZ_ASSUMED`. Offset-aware ISO strings are output only when a zone is known.
- **Past references** ("yesterday", "last year"): resolved, but flagged `PAST_DATE` when attached to a to-do relation.
- **Relation routing:** `DUE_ON` → `due`, `SCHEDULED_ON` → `scheduled`. The hint changes interpretation only for deadline phrasing ("by Friday" is an end-of-day deadline on Friday, not a scheduled start).

### Step 3 — Relation/label reconciliation (`src/pipeline/uncertainty.py`, part 1)

A cue check on the text before the temporal span ("by", "before", "due", "no later than", "until", "deadline", "EOD/COB") compared with the predicted label:

- cue present but label SCHEDULED_ON → raise `DATE_RELATION_CONFLICT`, set `due` as the *proposed* interpretation, keep the model's label in provenance, and **never silently overwrite** it;
- no cue but label DUE_ON → `info`-level note only.

This is the targeted fix for the Phase 3 finding that "by Friday" is predicted SCHEDULED_ON.

### Step 4 — Identity resolution (`src/pipeline/identity_resolution.py`)

`resolve_assignee(person_span | None, task_text, envelope, registry) -> AssigneeResolution`

- **Named spans:** normalise (case, `Mr./Ms.`, punctuation, trailing commas) and match in order: exact alias/email → `RESOLVED`; a first name unique among participants → `RESOLVED` with `basis="unique_first_name"` and an `info` flag so the reviewer can see how it matched; several matches → `AMBIGUOUS` with candidates; no match → `UNKNOWN_PERSON`.
- **First person** ("I'll send", "let me", "I will"): resolves to the sender only when the task text carries a first-person commitment cue. Otherwise `UNASSIGNED`.
- **Second person/imperative with no named assignee** ("Please send the report"): resolves to the single non-sender recipient when exactly one exists. With several, it is `UNASSIGNED` with a question ("Who should send the report?"). With none, `UNASSIGNED`.
- **Collective words** (all, everyone, team, "DPC", organisation names): `UNSUPPORTED_GROUP`, routed to review. GROUP is out of the Phase 3 neural scope.
- **Multiple links** on one task: `MULTIPLE_ASSIGNEES`, owner null, candidates kept.
- **Registry helpers:** `Participant` registry loader (JSON). A separate `registry_from_mailex_record()` parses `K. Bass [mailto:…]` and the recipient tokens. It is marked `low_trust` and used only for corpus experiments.

### Step 5 — Uncertainty flags and clarification questions (`src/pipeline/uncertainty.py`, part 2)

Rule-based, with a fixed flag catalogue. Each flag has a code, a severity and a question template:

| Code | Trigger | Question template |
|---|---|---|
| `NO_ASSIGNEE` / `AMBIGUOUS_ASSIGNEE` / `UNKNOWN_PERSON` / `UNSUPPORTED_GROUP` / `MULTIPLE_ASSIGNEES` | assignee statuses above | "Who should {task}?" |
| `DATE_UNRESOLVED_NO_ANCHOR` | relative date, no reference timestamp | "What is the date of '{raw}'?" |
| `DATE_AMBIGUOUS` | same-weekday or two candidates | "Which {raw} did you mean ({a} or {b})?" |
| `DATE_EVENT_CONDITION` | event-conditional date | "When is '{raw}' expected, or which task does it wait for?" |
| `DATE_VAGUE` / `DATE_PARTIAL` | vague or year-missing values | "Is there a firm date for '{raw}'?" |
| `DATE_RELATION_CONFLICT` | Step 3 | "Is '{raw}' a deadline or a scheduled time?" |
| `COMPETING_DATES` | two temporals with the same relation to one task | "Which date applies: '{a}' or '{b}'?" |
| `PAST_DATE` | resolved date before the reference time | "'{raw}' is in the past. Is this task already done?" |
| `WEAK_RELATION_SCORE` | neural score below the calibrated threshold | "Is '{target}' really linked to '{task}'?" |
| `MODEL_DISAGREEMENT` | neural and rule linkers choose different targets/labels | "The extractors disagree about '{task}'. Which link is right?" |
| `UNSUPPORTED_PREREQUISITE` | rule-path DEPENDS_ON with no resolvable prerequisite task | "Which task must happen before {task}?" |

`review_required = any(flag.severity != "info")`. Scores are described as *uncalibrated* everywhere.

**Threshold tuning (SILVER, provisional).** Use the saved Phase 3 validation predictions to produce a selective-prediction table: for min-score thresholds from 0.5 to 0.99, report positive-link precision, recall and the share of predictions auto-passed, with thread-level bootstrap intervals. Select the default threshold on validation only, and label it provisional. The test split stays untouched.

### Step 6 — Candidate assembly (`src/pipeline/task_fields.py`)

`build_task_candidates(envelope, entities, neural_relations, rule_relations, registry, config) -> list[TaskCandidate]`

- Groups relations per TASK span, resolves the assignee, normalises due and scheduled values, runs Steps 3 and 5, and fills in provenance (neural/rule/both, model versions, rule IDs).
- Includes TASK spans with no links, as candidates with `NO_ASSIGNEE` and no date. Nothing is dropped.
- CLI: `scripts/run_phase4_pipeline.py --text ... --sender ... --recipients ... --timestamp ... [--timezone ...]`. It runs the existing entity extractor (or accepts `--entities`) and the Phase 3 `RelationPredictor`. Rules are used only when asked for explicitly, and never as a silent fallback.

### Step 7 — Evaluation on the current data (`scripts/evaluate_phase4.py`)

All reported as **functional and provisional**, not accuracy against human labels.

1. **Regression fixtures** (`tests/fixtures/temporal_cases.json`, about 80 hand-written cases): each has an expression, a reference timestamp and timezone, and the expected status and value. They cover every grammar family, ambiguity, missing-anchor cases and conventions. These are *functional tests I author, not an independent benchmark*, and the report says so.
2. **Corpus coverage report (train + validation only, test untouched):** the distribution of `TemporalValue.status` over all annotated TEMPORAL spans, both with no anchor (the corpus reality) and with a clearly marked **illustrative** anchor (to exercise the relative-date paths). Also the share of expressions that need an anchor, and a list of unparseable spans for grammar review.
3. **Assignee resolution distribution** on validation, using the low-trust MailEx registry: the share of tasks that are resolved, ambiguous, unknown, group or unassigned.
4. **Flag rates** on Phase 3 validation predictions: how often each flag fires, the review rate, and the neural–rule disagreement rate.
5. **Selective-prediction table** from Step 5.
6. **Output:** `results/phase4/REPORT.md` plus JSON, listing the limitations.

### Step 8 — Tests

New files: `tests/test_temporal_normalize.py`, `tests/test_identity_resolution.py`, `tests/test_uncertainty.py` and `tests/test_task_fields.py`.

- **Temporal:** relative dates against fixed anchors, timezone and DST boundaries, missing anchor, missing year, same-weekday ambiguity, `EOD`/`COB` convention, scheduled vs deadline phrasing, event-conditional and vague terms, time-only combined with a date, and week/month ranges.
- **Identity:** exact alias, unique first name, ambiguous first name, unknown person, `I` and `you` rules, one vs many recipients, group words, and multiple assignees.
- **Uncertainty:** each flag fires on its trigger and stays silent otherwise, cue-based label conflict, and competing dates.
- **Assembly:** end-to-end on a handful of messages, with unresolved fields **surviving into the output** (the roadmap's completion test), no machine-date fallback (patch the clock to prove it), and JSON round-trip of the contracts.
- All existing tests (123) must keep passing.

---

## 5. Deliverables

```
src/pipeline/contracts.py
src/temporal/normalize.py                (+ src/temporal/__init__.py)
src/pipeline/identity_resolution.py
src/pipeline/uncertainty.py
src/pipeline/task_fields.py              (+ src/pipeline/__init__.py)
scripts/run_phase4_pipeline.py
scripts/evaluate_phase4.py
configs/phase4.json                      (EOD hour, weekday policy, flag severities, score threshold)
tests/test_temporal_normalize.py, test_identity_resolution.py, test_uncertainty.py, test_task_fields.py
tests/fixtures/temporal_cases.json
results/phase4/REPORT.md (+ JSON)
```

## 6. Acceptance criteria

- [ ] Fixture cases pass, covering relative dates, timezones, missing metadata, ambiguous dates, scheduled vs deadline, multiple recipients and no-assignee cases.
- [ ] With no reference timestamp, no relative date is ever resolved (verified by a clock-patched test).
- [ ] `due` and `scheduled` are separate fields, and an unresolved field keeps its raw text, status and a clarification question in the output.
- [ ] Assignee resolution never auto-picks among several candidates, and `I`/`you` resolve only under their stated conditions.
- [ ] Every candidate is traceable: evidence text, relation provenance, model versions, rule IDs.
- [ ] Threshold and flag-rate numbers are reported as SILVER/provisional, with the test split unread.
- [ ] The existing 123 tests still pass.

## 7. Risks

| Risk | Mitigation |
|---|---|
| The corpus has no timestamps, so the real-data resolution rate is low and the report may look unimpressive. | Report this explicitly as a data limitation. The app (Phase 7) supplies timestamps from chat messages. Fixtures test the resolved paths. |
| A rule grammar can miss expressions that `dateparser` would catch. | Unparseable spans are listed in the report and map to `UNPARSEABLE`, never a guess. The grammar is extended from that list. `dateparser` can be added later behind the same interface. |
| Weekday and "next/this" conventions differ between people. | The conventions are explicit, tested and configurable. Ambiguous cases return both candidates. |
| Over-flagging makes everything need review. | The review rate is measured and reported. Severities can be tuned in `configs/phase4.json` without code changes. |
| MailEx sender/recipient parsing is noisy. | Marked low-trust and used only for corpus experiments. The app path uses clean `Participant` records. |

## 8. Order and checkpoints

1. Step 1 (contracts) and Step 2 (temporal normaliser plus its tests) first. **Checkpoint:** I report the fixture pass rate and the list of unparseable corpus spans.
2. Steps 3 to 5 (label reconciliation, identity, flags) with their tests.
3. Step 6 (assembly and CLI), then Step 7 (evaluation report), then a full test run.
4. A final summary: what resolves, what is deliberately left unresolved, and the provisional numbers.

**Out of scope:** reconciliation and lifecycle (Phase 5), the dependency graph (Phase 6), API and UI (Phase 7), calibration beyond the validation threshold table, any human-reviewed GOLD data, and use of the test split.
