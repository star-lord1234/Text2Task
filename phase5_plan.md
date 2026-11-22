# Phase 5 Plan — Task Reconciliation and Lifecycle

**Status:** Draft for your review. Nothing in this plan has been implemented.
**Source:** `remaining_phases.md` §6, checked against the repo, the Phase 3 and 4 outputs, and the corpus.
**Goal:** Keep **one persistent task per piece of work** as conversation turns create, discuss, update or close it. The entity and relation models only find spans and links. They do not know whether a message means "new task", "same task, new deadline" or "that task is done". Phase 5 adds that layer as a conservative, transparent state machine. It is not a trained model.

It consumes the Phase 4 `TaskCandidate` records and produces **proposed operations**. A reviewer approves, edits or dismisses each one, and only then does the persistent task store change. Every change is appended to an immutable history.

---

## 1. What the repo check found

| Finding | Evidence | Consequence |
|---|---|---|
| **The corpus barely contains update messages.** Of 510 train+validation emails: completion cues ≈ 17, cancellation ≈ 8, reschedule ≈ 11, acceptance ("works for me", "confirmed") ≈ 6, reassignment ≈ 1. | regex scan | There is no data to measure reconciliation accuracy quantitatively, and no GOLD data is available. Evaluation has to rest on **scripted multi-turn scenarios**, which are functional tests, not a benchmark. Corpus runs are for qualitative inspection and rate statistics only. |
| **Threads are short.** Only 89 of 415 threads have more than one turn, and the longest has 4 turns. | `thread_id` counts | Cross-turn matching is exercised on a handful of real threads. Scenarios need to carry most of the testing. |
| **Update messages often have no TASK span.** "Monday works." and "Done." contain no task phrase, so Phase 4 creates no candidate for them. | design analysis | The reconciler cannot work only from Phase 4 candidates. It must also read the message text and its non-task entities (TEMPORAL, PERSON) sentence by sentence. |
| The Phase 4 `MessageEnvelope` has no reply reference. | `contracts.py` | Add an optional `in_reply_to` field. This is backward compatible, and Phase 7 chat supplies it. |
| Phase 4 `TaskCandidate` already carries owner resolution, `due`/`scheduled` values with unresolved statuses, flags, provenance and evidence. | Phase 4 | Task creation maps from it directly. Unresolved fields are stored as they are and never filled in. |
| Dependencies appear only as proposed rule-path entries on candidates. | Phase 4 | Phase 5 **stores** proposed dependency edges separately. Cycle checks and blocked/ready states belong to Phase 6. |

---

## 2. Decisions to confirm before implementation

Each has a default. Tell me which to change.

1. **Storage.** Use stdlib `sqlite3` now, behind a small `TaskStore` interface, with an in-memory mode for tests. Phase 7 then reuses it. *Alternative: in-memory only until Phase 7.*
2. **Who may change a deadline.** A declarative change ("the deadline is now Monday") by the task's creator or current owner becomes a *direct* proposal. Anyone else, or any wording like "could we move it?", becomes a *proposal needing confirmation* from the creator or owner. Both still go through review. *Default: as described.*
3. **Date changes cover both fields.** The roadmap names `PROPOSE_DUE_DATE_CHANGE`. I'll keep the operation names but carry a `field` of `due` or `scheduled`, so "move the meeting to Monday" works too.
4. **Status vocabulary.** `open`, `in_progress`, `completed`, `cancelled`. `blocked` stays a derived graph state (Phase 6) and is never stored.
5. **Completion authority.** A completion statement by the current owner is accepted as a normal proposal. By anyone else, it gets a `THIRD_PARTY_COMPLETION` flag. Completion with no matching task is `NO_ACTION` plus a review flag, never a guess.
6. **Matching signals.** Lexical and structural signals only (see §5). Local sentence embeddings (the multilingual MPNet model is already cached) stay an *optional ablation behind a flag*, off by default, and can never override direct evidence.
7. **Audit clock.** History timestamps come from an injected clock (tests use a fixed one, production uses UTC system time). This is a different thing from the Phase 4 rule, which forbids the machine clock for *interpreting dates in messages*. I'll state that boundary in the code and the docs.
8. **Review mode only.** No auto-apply. An `auto_apply` hook may be left as a disabled stub, but nothing uses it. False-auto-apply reporting becomes relevant only if you enable it later.
9. **Reopening.** Not supported in the MVP. A completed task that gets a "not done after all" message produces a review flag, and no state change.
10. **Message envelope.** Add the optional `in_reply_to`. No other contract changes.

---

## 3. Data contracts and schema (Step 1)

New `src/reconciliation/models.py`: dataclasses, JSON-serialisable, with `schema_version`.

- **`Task`**: `task_id` (stable, `T-<n>` per workspace), `workspace_id`, `thread_id`, `title`, `aliases[]` (alternate wordings from restatements, used only for matching), `owner_id|null`, `due` and `scheduled` (Phase 4 `TemporalValue` dicts with their status and raw text), `status`, `source_message_id`, `evidence_text`, `version`, `created_by`, `created_at`, `last_touched_message_id`, `provenance`.
- **`PendingChange`**: a proposed due/scheduled change waiting for confirmation, stored with the task but *not applied*.
- **`ProposedOperation`**: `proposal_id`, `operation` (CREATE_TASK, UPDATE_ASSIGNEE, PROPOSE_DUE_DATE_CHANGE, CONFIRM_DUE_DATE_CHANGE, UPDATE_STATUS, COMPLETE_TASK, CANCEL_TASK, ADD_DEPENDENCY, NO_ACTION), `task_id|null`, `field`, `before`/`after`, `source_message_id`, `evidence_span`, `match` (the full match explanation), `flags[]` (Phase 4 flags carried over plus the new codes below), `needs_confirmation_from[]`, `status` (pending, applied, dismissed, superseded, failed), `source_kind`, `idempotency_key`.
- **`HistoryEvent`**: **append-only**. Fields: `event_id`, `task_id`, `proposal_id`, `message_id`, `actor`, `operation`, `field`, `before`, `after`, `timestamp`, `source_kind` (`neural`, `rule`, `scripted`, `human`), `note`.
- **`DependencyEdge`**: `edge_id`, `dependent_task_id`, `prerequisite_task_id`, `status` (proposed, accepted, rejected), `evidence`, `source_message_id`, `source_kind`, `score|null`, `reason`. Stored only. Phase 6 validates it.

SQLite tables: `schema_meta`, `tasks`, `proposals`, `history`, `dependencies`, `processed_messages`, `idempotency_keys`. History immutability is enforced by SQLite triggers that reject `UPDATE` and `DELETE`.

## 4. Task store (Step 2) — `src/reconciliation/store.py`

- `create_task`, `get_task`, `list_tasks(workspace, thread, status, owner)`, `record_proposal`, `list_pending`, `history_for`, `save_dependency`.
- **`apply_change(proposal_id, actor, expected_version, idempotency_key, edits=None)`**, in **one transaction**:
  1. replay an already-seen idempotency key and return the earlier result, with no second write;
  2. reject with `STALE_VERSION` if `task.version != expected_version` (nothing is written, and the conflict is surfaced);
  3. validate the status transition (§6) and the owner/date consistency;
  4. update the task, bump `version`, write the history event(s) with before/after, and mark the proposal applied.
- `dismiss(proposal_id, actor, reason)` and `apply_manual_edit(...)`. The manual edit uses the same version check and history path with `source_kind = "human"`. Phase 7 needs it.
- The stable `task_id` is never reassigned or reused.

## 5. Intent detection and operations (Step 3) — `src/reconciliation/cues.py`, `operations.py`

Intent is decided **per sentence**, not per message. The sentence splitter keeps character offsets so evidence can be highlighted.

| Operation | Triggers (rule-based, with context) | Required evidence | Never fires when |
|---|---|---|---|
| CREATE_TASK | An instruction, request or first-person commitment with a TASK candidate ("Bianca, prepare the report by Friday", "I'll send the notes") | A Phase 4 candidate and no strong match to an existing task | The sentence is historical ("The API failed yesterday"), a pure question, or an FYI |
| UPDATE_ASSIGNEE | Explicit reassignment ("can you take this over", "Dev will do it instead", "reassigning to Dev") | A matched referent and a resolved new assignee different from the current owner | The new person is ambiguous or unknown (`flag`, no change) |
| PROPOSE_DUE_DATE_CHANGE | Modal or question change ("could we move it to Monday?", "can we push to the 20th") or a declarative change ("deadline is now Monday") | A matched referent and a normalised new date | The date is unresolved (the unresolved value is carried and flagged, never guessed) |
| CONFIRM_DUE_DATE_CHANGE | Acceptance ("Monday works", "sounds good", "ok") | A **pending** proposal on the referent, from a different speaker than the proposer, with no conflicting date in the reply | No pending proposal exists. A conflicting date ("Tuesday is better") becomes a *counter-proposal* that supersedes the old one |
| UPDATE_STATUS | "started working on it", "I'm on it" | A matched referent | The referent is completed or cancelled |
| COMPLETE_TASK | First-person or passive completion ("I've finished the report", "the report is done") | A matched referent. Negation ("haven't finished") and questions ("did you finish?") are excluded | There is no referent (→ `NO_ACTION` + review flag). Completion of an already-completed task is `NO_ACTION` |
| CANCEL_TASK | "cancel", "no longer needed", "scrap that", "don't need to" | A matched referent | A conditional ("if we cancel...") or a question |
| ADD_DEPENDENCY | An explicit prerequisite cue between two matched tasks, or the Phase 4 rule-path proposal | **Both** tasks matched | Either endpoint is unmatched (→ review flag) |
| NO_ACTION | History, questions, FYI, thanks, duplicates | | |

Each detection returns the operation, the sentence span, the cue, flags for negation and question form, a firmness tag (`declarative` or `tentative`), and the entity ids it relies on. Cues live in one versioned module with unit tests for each cue, its negation and its question form.

## 6. Matching (Step 4) — `src/reconciliation/matcher.py`

**Candidate retrieval:** tasks in the same workspace and thread, active by default. Completed or cancelled tasks are included only to detect duplicates and late replies.

**Transparent additive score.** Each signal is stored in the explanation:

| Signal | Behaviour |
|---|---|
| Explicit task id (`T3`, `#3`) | decisive |
| `in_reply_to` points at the message that created or last touched the task | strong |
| Same normalised action + object phrase (light stemming, stopwords removed, verb+object containment/Jaccard) | strong |
| Anaphora ("it", "this", "that") | only when exactly one task was touched within the last N turns (config), otherwise ambiguous |
| Speaker/owner relation (the owner reports completion; the proposer is not the confirmer) | supporting |
| Recency | small tie-breaker |
| Optional embeddings similarity | supporting only, off by default |

**Outcomes** (thresholds in `configs/phase5.json`, set on scripted scenarios and documented, never tuned on test):
- **MATCHED:** score ≥ high threshold **and** a margin over the runner-up.
- **AMBIGUOUS_REFERENT:** several plausible tasks. A review proposal lists the candidates, and **no task is modified**.
- **NO_REFERENT:** nothing plausible. Create operations may proceed. Update operations become `NO_ACTION` + flag.

**Duplicate handling:**
- *Repeated submission:* the idempotency key (workspace + message id + text hash) makes reprocessing return the same proposals and write nothing new.
- *Repeated request:* a CREATE intent that strongly matches an existing task with the same owner and date becomes `NO_ACTION`, linked as a restatement. If the date differs, it becomes a due-date change proposal with a `RESTATED_WITH_DIFFERENT_DATE` flag.

## 7. Reconciler (Step 5) — `src/reconciliation/reconciler.py`

`Reconciler(store, config, clock)`:

- `process_message(envelope, entities, candidates, workspace_id) → ReconcileResult(proposals, no_actions)` runs intent detection, matching, construction and validation, then **persists the proposals as `pending`**. It is idempotent per message.
- `accept(proposal_id, actor, expected_version)`, `edit_and_accept(...)`, `dismiss(...)` call the store.
- **Validation before a proposal is created:** owner is a known participant or null, dates are `TemporalValue`s with their status intact, the status transition is allowed, and dependency endpoints exist.
- **Allowed transitions:** `open → in_progress`, `open|in_progress → completed`, `open|in_progress → cancelled`. Anything from `completed`, and `cancelled → completed`, produces a `ILLEGAL_TRANSITION` flag and no change.
- **Pending changes:** a date-change proposal leaves the active date untouched. A later confirmation applies it. A dismissal, or a counter-proposal, leaves the old state or supersedes the old proposal. Both are recorded.
- **New reconciliation flags:** `AMBIGUOUS_REFERENT`, `NO_REFERENT`, `POSSIBLE_DUPLICATE`, `RESTATED_WITH_DIFFERENT_DATE`, `STALE_VERSION`, `CONFLICTING_PROPOSAL`, `THIRD_PARTY_COMPLETION`, `ILLEGAL_TRANSITION`, `UNRESOLVED_NEW_DATE`, `UNRESOLVED_NEW_OWNER`. Each carries a clarification question, as in Phase 4.

### Worked example (also scenario #1)

| Message | Expected operation | Result |
|---|---|---|
| Riya: "Bianca, prepare the report by Friday." | CREATE_TASK | Task T1, owner Bianca, due Friday |
| Riya: "Could we move it to Monday?" | PROPOSE_DUE_DATE_CHANGE | Friday stays active, Monday pending, needs confirmation from the owner |
| Bianca: "Monday works." | CONFIRM_DUE_DATE_CHANGE | On accept, T1 due = Monday, version 2, history event |
| Bianca: "I've finished the report." | COMPLETE_TASK | T1 completed, **no** new task |
| Bianca: "The API failed yesterday." | NO_ACTION | No task created |
| Riya (second task exists): "Is it done?" | NO_ACTION | A question, no state change |
| Riya: "Could we move the review to Monday?" (two active "review" tasks) | PROPOSE... flagged `AMBIGUOUS_REFERENT` | Nothing changes until a reviewer picks the task |

## 8. Evaluation and scenarios (Step 6)

Everything is **functional and provisional**. There is no GOLD data and the corpus holds almost no update messages.

1. **Scripted scenario suite** (`tests/fixtures/reconciliation_scenarios.json`, about 40 multi-turn scenarios I author): creation, due-date proposal/confirm/counter-proposal/dismissal, reassignment, status, completion, cancellation, negation, questions, anaphora, ambiguous referent, no referent, repeated message, restated request (same and different date), stale version, illegal transition, rejected proposals, manual edit, dependency proposal. Each lists the expected operations and final task states.
2. **Invariant and fuzz tests:** seeded random interleavings of messages and review actions must keep these true: task ids never change, versions are monotonic, history is append-only and chain-consistent (each `before` equals the previous `after`), replaying any message creates no new rows, and unmatched updates never modify a task.
3. **Reported metrics** (on the scenarios only): operation accuracy, **duplicate creation rate**, **incorrect-overwrite count** (target 0), ambiguous-update handling (all routed to review), stable-identity checks.
4. **Corpus pass** (`scripts/evaluate_phase5.py`): replay the 89 multi-turn train/validation threads through Phase 3, 4 and 5. Report operation-type counts, referent outcome rates, duplicate detections and the flag distribution. I will also write a small sample of flagged cases to `results/phase5/samples.md` for qualitative error analysis. These are **not** accuracy numbers. The sparse cue counts above are why.
5. **Report:** `results/phase5/REPORT.md` with the limitations stated up front.

## 9. Integration and CLI (Step 7)

- `scripts/run_phase5_pipeline.py --scenario file.json [--db path|:memory:]` replays messages through Phase 3, 4 and 5 and prints proposals and final task states. Accepting is a scripted review step in the scenario file.
- The library API is what Phase 7's FastAPI layer will call. No web code is written in this phase.

## 10. Deliverables

```
src/reconciliation/__init__.py, models.py, store.py, cues.py, operations.py, matcher.py, reconciler.py
configs/phase5.json                      (thresholds, anaphora window, cue-set version, auto_apply: false)
scripts/run_phase5_pipeline.py, scripts/evaluate_phase5.py
tests/test_reconciliation_store.py, test_reconciliation_cues.py, test_reconciliation_matcher.py,
tests/test_reconciliation.py, tests/test_reconciliation_invariants.py
tests/fixtures/reconciliation_scenarios.json
results/phase5/REPORT.md, report.json, samples.md
src/pipeline/contracts.py                (add optional in_reply_to; backward compatible)
```

## 11. Acceptance criteria

- [ ] Stable task ids survive creation, date change, reassignment, completion and cancellation.
- [ ] Repeated messages and restated requests never create a duplicate task (checked in scenarios and the fuzz tests).
- [ ] Ambiguous or missing referents never modify any task. They produce a review proposal that names the candidates.
- [ ] Rejected and superseded proposals leave the task unchanged, and are recorded.
- [ ] Every applied change is atomic, version-checked and idempotent. A stale version is rejected with nothing written, and history is append-only (enforced by triggers).
- [ ] The history for any task reconstructs its current state, with before/after, actor, message id, timestamp and source kind on each event.
- [ ] Unresolved dates and owners carried from Phase 4 are preserved, never guessed.
- [ ] All existing tests (165) still pass.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Cue-based intent is brittle and will miss paraphrases, and email-style text differs from chat. | Conservative by design: when unsure, produce `NO_ACTION` or a flagged proposal, never a change. Cues are versioned and tested, and the report lists known misses. |
| No data to measure accuracy. | Scenarios and invariants give functional assurance only, and the report says so. Nothing is presented as accuracy. |
| Phase 4 may extract a completion sentence as a new TASK ("finished the report"). | Intent is decided first. A completion or status intent with a matched referent suppresses CREATE for that sentence. |
| Over-matching on common action words ("send", "review"). | Require verb **and** object overlap, a margin over the runner-up, and a recency limit. Ties become `AMBIGUOUS_REFERENT`. |
| The 90% review rate from Phase 4 will carry over. | Reported honestly. Thresholds and severities are configurable. |
| SQLite concurrency. | Single-writer transactions, WAL mode, and version checks. Adequate for the local MVP. |

## 13. Order and checkpoints

1. Steps 1 and 2 (models and store with their tests). **Checkpoint:** the store invariants pass.
2. Steps 3 and 4 (cues and matcher with tests).
3. Step 5 (reconciler) and the scenario suite. **Checkpoint:** I report scenario pass rate and any behaviour that I think needs your call.
4. Steps 6 and 7 (evaluation, corpus pass, CLI), then a full test run and a short summary.

**Out of scope:** a trained coreference or update-intent model, cross-thread coreference, graph validation, cycle detection and blocked/ready derivation (Phase 6), the API and UI (Phase 7), auto-apply, authentication, and any human-reviewed GOLD data.
