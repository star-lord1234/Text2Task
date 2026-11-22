# Phase 5 — Task reconciliation and lifecycle (FUNCTIONAL / PROVISIONAL)

Review mode only: the reconciler produces *proposals*; nothing changes a task until a reviewer accepts it.
There is **no labelled reconciliation data** and the corpus contains almost no update messages (about 17 completion, 8 cancellation,
11 reschedule, 6 acceptance and 1 reassignment cue across 510 emails), so none of this is accuracy against human judgement.
Train+validation only; the test split was never read. Raw numbers: `report.json`; corpus rows for reading: `samples.md`.

## 1. Scripted scenarios (developer-authored; extractor output is SCRIPTED, so these test reconciliation logic, not ML)
- **43 / 43 scenarios pass** (88 per-message operation checks, 0 mismatches).
  Thresholds were set while writing these scenarios, so the pass rate is a regression guard, not an independent measurement.
- **Duplicate creation:** 4 duplicate-attempt scenarios (replayed message, identical restatement, restatement with a new date,
  double accept) produced **0** extra tasks.
- **Incorrect overwrites:** **0** updates applied to a task that was not matched or reviewer-chosen;
  **0** resolved dates replaced by unresolved ones.
- **Ambiguous referents:** 2 raised; none changed any task until the reviewer chose one.
- **Stable identity / history:** 0 violations. Every scenario checks that history alone reconstructs each task's state and that task ids stay contiguous.
- Covered: create, propose/confirm/counter-propose/dismiss/decline date changes, direct changes by the creator, reassignment (named, single addressee,
  unresolved), status, completion, cancellation, illegal transitions, third-party completion, stale version, idempotent accept, manual edit,
  dependency (cue-based and Phase 4 rule path), reopen request, thread isolation, pending-review referents, message-id reuse.

## 2. Invariant fuzzing (200 seeds x 60 random steps = 12000 steps)
Random interleavings of messages, accepts, dismissals, replays and manual edits; after every step: ids never disappear, versions never decrease,
history is never rewritten, history reconstructs every task, replays write nothing, and every applied update had a matched referent.
**0 violations.** 688 random review actions were refused by the safety checks (stale versions, illegal
transitions, unresolved values, prerequisites pending), as intended. 1151 tasks were created and 539 updated, so the fuzz is not vacuous.
Mutation check: dropping history writes for `status` was caught in 5 of 15 seeds.

## 3. Corpus replay (415 threads, 89 multi-turn, 510 messages; annotated v1 entities -> Phase 3 neural relations -> Phase 4 -> Phase 5; simulated reviewer accepted creations only)
- Proposals: {"NO_ACTION": 959, "CREATE_TASK": 939, "PROPOSE_DUE_DATE_CHANGE": 4, "COMPLETE_TASK": 3, "UPDATE_STATUS": 1, "CANCEL_TASK": 1}.
- **939 creation proposals from 510 messages (about 1.8 per message).** The labelled task spans are noisy (many are not actionable) and the
  CREATE gate accepts a request cue, a deadline or a resolved owner, so most creations carry flags: NO_ASSIGNEE 278,
  WEAK_RELATION_SCORE 191, AMBIGUOUS_ASSIGNEE 78. In review mode every one still needs a human decision.
  This is the main thing to tune before relying on it.
- Update operations are rare (4 date-change, 3 completion, 1 status, 1 cancellation proposals).
  Referent outcomes for them: {'AMBIGUOUS_REFERENT': 5, 'MATCHED': 4}. Reading `samples.md`, most are plausible-looking but several are false positives on formal email text
  (for example "I reviewed your spreadsheets" read as a completion report). All ended flagged or ambiguous; **none was applied automatically**.
- Duplicates: 1 restatement and 8 possible-duplicate detections. Too few to say anything quantitative.
- Reading the samples led to four cue fixes (subordinate "when/once/if" clauses, announcements like "the meeting will be held", the noun "night shift",
  and downgrading unmatched date/status remarks to an info flag); regression tests were added.

## 4. Real-model check (live mode, 5-message example)
Entity checkpoint -> relation model -> Phase 4 -> Phase 5 on the plan's example. Creation, the date proposal ("to Monday" after a normaliser fix), the
confirmation and the completion all produced the expected proposals, and the history statement created nothing. The entity model split "by" and "Friday" into
two spans (surfaced as `COMPETING_DATES`) and labelled "Monday works" as one TEMPORAL span; the reconciler tolerated both. This is an anecdote, not a measurement.

## Limitations
- Cue-based intent is brittle: it misses paraphrases and misfires on formal email phrasing. It is built to fail safe (flag or no-op), not to be accurate.
- A message that refers to a task whose creation is still *pending review* cannot be matched (it gets `REFERENT_PENDING_REVIEW`); reviewers should accept creations in order.
  Messages are not re-processed after the fact.
- One primary intent per sentence; compound sentences ("done, and I'll send it Monday") yield only the first.
- `aliases` exist on tasks but nothing populates them yet. Matching is lexical (embeddings are an unused, off-by-default hook).
- Dependencies are stored as accepted/rejected edges with a placeholder validator (endpoints exist, no self-loop); cycle detection and blocked/ready belong to Phase 6.
- Reopening completed tasks is unsupported (flagged only). Groups and multiple owners are unsupported (flagged).
- The audit clock (history timestamps) reads UTC system time through an injectable clock; it is never used to interpret dates in messages.

## Addendum (Phase 7): four reconciliation extensions, re-evaluated
Phase 7 closed four gaps found while building the app (pronoun/anaphora referents, owner acknowledgement vs restatement, "Can someone ..." requests, and a
volunteer claiming an existing *unowned* task via `UPDATE_ASSIGNEE`; ambiguous unowned candidates raise a referent chooser instead of a guess).
Each has positive and negative regression tests (`tests/fixtures/reconciliation_scenarios_ext.json`, 32 scenarios; 75 scenarios total pass).
Mutation checks confirmed the negatives fail when the guard is removed (task owned by someone else, different action on the same object, closed task,
joint commitments such as "Ellen and I will ...", ambiguity collapsed to a guess).
Re-running the corpus replay and fuzzing on the final code: invariants held (0 violations over 12000 fuzz steps; 43/43 original scenarios) and the corpus
proposal counts equal the original baseline above (939 CREATE_TASK, 4 date-change, 3 completion, 1 status, 1 cancellation, 0 UPDATE_ASSIGNEE).
An intermediate version of the volunteer rule produced two UPDATE_ASSIGNEE proposals on formal email text ("Ellen and I just spoke ...", "I could leave work ...");
these were false positives, so the rule now requires a first-person commitment verb leading the sentence. Still a developer-authored, cue-based check, not an accuracy measurement.
