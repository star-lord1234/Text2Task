# Text2Task Annotation Guidelines v1.0

## Purpose and stopping point

These guidelines define the pilot annotation format for extracting task graphs from one email turn at a time while retaining thread identity. They are intentionally conservative. MailEx annotations and candidate-selection flags may help locate examples, but they are not Text2Task gold labels.

Do not begin bulk LLM labeling under this version. First validate the schema, annotate a small human-reviewed pilot, measure disagreement, revise the guidelines if needed, and adjudicate the pilot.

The machine contract is `configs/text2task_schema_v1.json`. Character offsets are measured against the record's stored `text`, not `text_raw`, tokens, or rendered email.

## Reference-resolution decision

Text2Task v1 does **not** include an entity type for reference mentions. Pronouns such as “I,” “she,” “they,” “it,” and “this report” therefore do not receive an invented PERSON, GROUP, or ARTIFACT label solely to enable a relation.

`REFERS_TO` is deferred to a separate resolution layer. In v1:

- `REFERS_TO` is not allowed in stored `relations` or `relation_candidates`.
- `reference_resolution.status` must be `DEFERRED_NO_REFERENCE_SPANS` and `mentions` must be empty.
- A task whose owner is expressed only by a pronoun has no `ASSIGNED_TO` edge. Mark `ASSIGNEE` in `unresolved_fields` and set `ambiguous=true`.
- Do not resolve a pronoun to a nearby name even when the answer seems obvious. That decision belongs to the later resolution layer.

This avoids an inconsistent mixture in which some reference mentions have token spans and others do not.

## Record structure

Before annotation, `text2task_annotations` may be `null`. A completed annotation set contains:

- `schema_version`: exactly `1.0.0`.
- `annotation_status`: `DRAFT`, `REVIEWED`, or `ADJUDICATED`.
- `annotator_id`: required in practice and machine-required for reviewed or adjudicated records.
- `entities`: character-offset spans.
- `relations`: positive task-graph edges only.
- `relation_candidates`: optional positive or `NONE` candidate pairs for relation-classification experiments.
- `reference_resolution`: the fixed deferred-reference marker described above.
- `notes`: concise adjudication or uncertainty notes.

Entity IDs are local to a record and use `e1`, `e2`, and so on. Relation IDs use `r1`, `r2`, and so on. Candidate-pair IDs use `rc1`, `rc2`, and so on.

## Span rules

All spans use half-open offsets `[start, end)`. The stored span text must equal `record.text[start:end]` exactly, including case and punctuation inside the span.

Use the smallest span that preserves the entity's meaning:

- TASK: the actionable predicate and necessary object or complement. Exclude greetings, politeness markers, assignees, and temporal modifiers unless they are grammatically inseparable. Include explicit negation in a negative instruction.
- PERSON: the explicit personal name only. Titles may be included when needed to identify the named person.
- GROUP: the explicit named team, department, committee, or collective.
- TEMPORAL: the complete date, time, duration, deadline, or relative temporal phrase.
- EVENT: the smallest occurrence or state needed to understand a task or dependency.
- ARTIFACT: the explicit document, file, report, attachment, deliverable, or other work product.

Do not force spans into BIO tags. The v1 representation is a list of independent character spans and allows overlap. A TASK may contain or overlap an ARTIFACT, for example TASK “update the report” and ARTIFACT “report.” Exact duplicate entities with the same type and offsets are invalid.

## Entity definitions

### TASK

Annotate work that is actually requested, committed, or planned. A TASK must describe an actionable step, not merely a topic, desire, hypothetical possibility, completed historical occurrence, or informational statement.

Requests include direct imperatives, interrogative requests, and clearly intended indirect requests. Commitments include explicit promises or plans by a speaker. Planned work must be sufficiently concrete to act on.

Do not create a new TASK merely because a sentence reports that something happened in the past. A completion statement can update an already established thread task when the identity is supported; otherwise annotate a relevant EVENT, PERSON, TEMPORAL, or ARTIFACT only.

### PERSON

Annotate explicitly named individuals, such as “Alice Chen” or “Dr. Patel.” Do not annotate pronouns, email roles such as “the sender,” or unnamed descriptions such as “the analyst.”

### GROUP

Annotate explicitly named collectives such as “Legal Operations,” “Risk Committee,” or “West Power Desk.” Generic mentions such as “everyone,” “someone,” “the team,” or “management” are not GROUP unless the text establishes them as a specific named collective.

### TEMPORAL

Annotate dates, times, durations, relative expressions, and vague but explicit temporal phrases: “Friday,” “at 3 PM,” “for two weeks,” “tomorrow,” and “soon.” A vague phrase may still be TEMPORAL; mark the affected TASK ambiguous when it prevents a precise interpretation.

### EVENT

Annotate an occurrence or state only when it matters to a task or prerequisite. Examples include “the audit closes,” “approval is received,” or “the server is restored.” Do not annotate every factual event in an email.

### ARTIFACT

Annotate an explicit document, file, report, form, presentation, attachment, or deliverable. The artifact may overlap a TASK. Do not label abstract information as ARTIFACT unless it is described as a concrete work product.

## Task attributes

Every TASK has a `task_attributes` object. Every non-TASK entity has `task_attributes: null`.

### `operation` 

- `CREATE`: introduces a new task instance or requests a new action. This does not require the surface verb “create.” “Send the report” normally creates a new task assignment.
- `UPDATE`: changes an existing task, artifact, schedule, or plan.
- `COMPLETE`: requests or records completion/closure of an established task.
- `CANCEL`: requests or records stopping, withdrawing, or canceling an established task.
- `UNKNOWN`: the operation cannot be determined. Add `OPERATION` to `unresolved_fields` and set `ambiguous=true`.

A proposed change may be a pending UPDATE task, but it is not evidence that the underlying change has occurred.

### `status`

- `PENDING`: requested, committed, or planned work not asserted complete.
- `COMPLETED`: the text explicitly establishes completion of the identified task.
- `CANCELED`: the text explicitly establishes cancellation of the identified task.
- `UNKNOWN`: status cannot be determined. Add `STATUS` to `unresolved_fields` and set `ambiguous=true`.

### `negated` and `ambiguous`

Set `negated=true` when the task predicate is explicitly negated or prohibited, as in “do not send.” Negation is not the same as cancellation: use `operation=CANCEL` only when the instruction stops or withdraws an action.

Set `ambiguous=true` when an essential interpretation is unresolved, including pronoun-only ownership, unclear task boundaries, competing dates, an unresolved cross-email match, or unknown operation/status. Explain unusual cases in `notes`.

### Missing and unresolved information

Use `missing_fields` when the email simply does not express an assignee or temporal value. Use `unresolved_fields` when relevant evidence exists but cannot be resolved safely.

- A TASK without `ASSIGNED_TO` must mark `ASSIGNEE` as either missing or unresolved.
- A TASK without `DUE_ON` or `SCHEDULED_ON` must mark `TEMPORAL` as either missing or unresolved.
- A field cannot be both missing and unresolved.
- Never invent a person, group, date, or time from common sense or metadata not represented in the annotation.

## Relation rules

Stored `relations` contain positive graph edges only. `NONE` is never a graph edge.

### `ASSIGNED_TO`

Direction: TASK → PERSON or GROUP.

Create the edge only when the text explicitly names the owner or the ownership follows directly without reference resolution. Pronoun-only ownership remains unresolved in v1.

### `DUE_ON`

Direction: TASK → TEMPORAL.

Use for a completion boundary: “by Friday,” “no later than 5 PM,” or “due tomorrow.” A deadline answers when the task must be finished.

### `SCHEDULED_ON`

Direction: TASK → TEMPORAL.

Use for the intended execution, start, meeting, appointment, or activity time: “meet Monday,” “run the job at 2 PM,” or “start next week.” A scheduled time answers when the task is intended to occur, not when it must be complete.

Do not create both relation types for the same task and temporal span unless the text explicitly gives the time both meanings.

### `DEPENDS_ON`

Direction: TASK → TASK or EVENT.

Create this edge only when completing or starting the source task is contingent on the target task/event, or the target provides a necessary input or authorization. Pure chronology is not enough. Words such as “after,” “before,” “once,” and “when” are signals to inspect, never automatic dependency labels.

### Relation evidence and explicitness

Every positive relation stores `relation_evidence` as one exact, contiguous text span. Select the smallest contiguous span that supports the edge; use the whole sentence if shorter fragments would lose the connection.

- `EXPLICIT`: the relation is directly stated by syntax or lexical wording.
- `INFERRED`: the relation is supported by the text but requires a limited discourse inference. The evidence still must be exact text.

Set relation-level `ambiguous=true` when the edge is retained for review but its interpretation is uncertain. Do not use inference to invent unstated owners or dates.

## Relation candidate pairs and `NONE`

`relation_candidates` is optional training metadata for candidate-pair classification. A `NONE` pair says that two annotated entities were considered but have no supported relation. For `NONE`, both `relation_evidence` and `explicit_vs_inferred` must be `null`.

A positive candidate pair uses the same endpoint rules as the corresponding stored relation and must include exact evidence and explicitness. Gold graph consumers should read `relations`, not treat candidate pairs as edges.

## Cross-email task identity

Use `thread_task_id` to preserve task identity across turns only when the match is supported by strong evidence such as the same explicit artifact/action, a direct reply, or an unambiguous status update.

- `LOCAL_ONLY`: no cross-email match is asserted; `thread_task_id` is null.
- `RESOLVED`: the match is supported; assign the same deterministic `thread-task:<thread>:<task>` ID to each mention.
- `UNRESOLVED`: a match is plausible but unsafe; keep `thread_task_id` null, add `CROSS_EMAIL_IDENTITY` to `unresolved_fields`, set `ambiguous=true`, and explain in `notes`.

Do not create cross-record relation endpoints in v1. Cross-email continuity is represented by the shared task ID.

## Annotation workflow

1. Read the current email and enough preserved thread context to understand references, without copying quoted text into current-email spans.
2. Mark actual TASK spans. If there are no tasks, keep the task graph empty.
3. Mark named people/groups, temporal expressions, relevant events, and artifacts.
4. Assign task operation, status, negation, ambiguity, missing fields, unresolved fields, and identity status.
5. Add only supported positive relations with exact evidence.
6. Add `NONE` candidate pairs only if the relation-classification experiment requests them.
7. Validate the record. Resolve all validation failures before review.
8. Record genuine interpretation questions in `notes`; never repair uncertainty by inventing a label.

## Worked examples

Bracket notation below illustrates spans. It is not the stored format. Offsets in JSON must point to the unbracketed source text.

### Example 1 — direct request, named owner, deadline

Text: “Alice, please send the report by Friday.”

- Entities: PERSON “Alice”; TASK “send the report”; ARTIFACT “report”; TEMPORAL “Friday.”
- Relations: `ASSIGNED_TO(send the report, Alice)` and `DUE_ON(send the report, Friday)`, both explicit.
- Task: `operation=CREATE`, `status=PENDING`, `negated=false`, `ambiguous=false`.

### Example 2 — commitment with first-person pronoun

Text: “I will prepare the deck tomorrow.”

- Entities: TASK “prepare the deck”; ARTIFACT “deck”; TEMPORAL “tomorrow.”
- Relation: `SCHEDULED_ON(prepare the deck, tomorrow)`.
- No PERSON and no `ASSIGNED_TO`: “I” is a deferred reference mention. Mark `ASSIGNEE` unresolved and the task ambiguous.

### Example 3 — explicitly named group owner

Text: “Risk Committee will review the proposal.”

- Entities: GROUP “Risk Committee”; TASK “review the proposal”; ARTIFACT “proposal.”
- Relation: `ASSIGNED_TO(review the proposal, Risk Committee)`.
- Mark TEMPORAL missing.

### Example 4 — multiple tasks with different owners

Text: “Alice will draft the memo, and Bob will approve it.”

- Entities: PERSON “Alice”; TASK “draft the memo”; ARTIFACT “memo”; PERSON “Bob”; TASK “approve it.”
- Add `ASSIGNED_TO(draft the memo, Alice)`.
- Do not add `ASSIGNED_TO(approve it, Bob)` in v1 if the TASK object itself is only the pronoun “it”? Ownership is explicit from “Bob,” so the owner edge is allowed; the artifact reference remains unresolved. Mark the second task's artifact interpretation ambiguous, not its owner.
- Do not add `DEPENDS_ON` unless the text or context establishes that approval waits for drafting.

### Example 5 — planned execution time

Text: “The Operations Team will run the migration at 2 PM.”

- GROUP “Operations Team”; TASK “run the migration”; EVENT “migration”; TEMPORAL “at 2 PM.”
- Add `ASSIGNED_TO` and `SCHEDULED_ON`, not `DUE_ON`.

### Example 6 — completion deadline

Text: “Submit the filing no later than 5 PM.”

- TASK “Submit the filing”; ARTIFACT “filing”; TEMPORAL “no later than 5 PM.”
- Add `DUE_ON`. Owner is missing.

### Example 7 — deadline and scheduled activity in one email

Text: “Send the slides by Friday; present them on Monday.”

- TASK “Send the slides” with `DUE_ON` → “Friday.”
- TASK “present them” with `SCHEDULED_ON` → “Monday.”
- Do not attach Monday as another deadline for sending.
- “them” is not an ARTIFACT span in v1; its resolution is deferred.

### Example 8 — multiple deadlines

Text: “Send the draft by Tuesday and the final report by Friday.”

- Annotate two TASKs because the draft and final are distinct deliverables.
- ARTIFACT “draft” and ARTIFACT “final report.”
- Attach Tuesday only to the draft task and Friday only to the final-report task.

### Example 9 — two constraints on one task

Text: “Upload the file by Friday, no later than 5 PM.”

- One TASK “Upload the file” and ARTIFACT “file.”
- TEMPORAL “Friday” and TEMPORAL “5 PM” may each receive a `DUE_ON` edge because both independently constrain the same completion boundary.
- If the source instead says “Friday at 5 PM,” prefer one combined TEMPORAL span.

### Example 10 — past occurrence is not automatically a task

Text: “Alice sent the report yesterday.”

- PERSON “Alice”; EVENT “sent”; ARTIFACT “report”; TEMPORAL “yesterday.”
- No TASK merely because a task-like verb appears in the past.
- If thread context unambiguously establishes this as completion of an existing task, annotate a task update under that shared `thread_task_id`; otherwise keep it an event.

### Example 11 — explicit completion update

Prior email: “Alice, prepare the report.” Current email: “The report is complete.”

- With a strong thread match, annotate TASK “report is complete” or the minimal completion predicate, `operation=COMPLETE`, `status=COMPLETED`, and reuse the resolved `thread_task_id`.
- Without a strong match, annotate EVENT “report is complete,” ARTIFACT “report,” and mark any suspected task identity unresolved rather than forcing it.

### Example 12 — proposed change is not a confirmed update

Text: “Could we move the review meeting to Monday?”

- This is a pending request to update the schedule: TASK “move the review meeting to Monday,” `operation=UPDATE`, `status=PENDING`.
- TEMPORAL “Monday” may have an explicit but ambiguous `SCHEDULED_ON` edge because acceptance is not yet known.
- Do not mark the meeting as already rescheduled or completed.

### Example 13 — cancellation request

Text: “Bob, please cancel the vendor call.”

- PERSON “Bob”; TASK “cancel the vendor call”; EVENT “vendor call.”
- `operation=CANCEL`, `status=PENDING`, `negated=false`.
- Add explicit `ASSIGNED_TO` to Bob. Do not set `status=CANCELED` until cancellation is asserted as completed.

### Example 14 — canceled occurrence, not a new task

Text: “The vendor call was canceled yesterday.”

- EVENT “vendor call was canceled”; TEMPORAL “yesterday.”
- No new TASK unless this is a supported status update to an existing thread task.
- If linked, the established task has `operation=CANCEL` and `status=CANCELED`.

### Example 15 — negative instruction

Text: “Do not send the draft to the client.”

- TASK span includes the negation: “Do not send the draft.”
- ARTIFACT “draft.”
- Set `negated=true`. Use `operation=CANCEL` only if context shows a previously planned send is being stopped; otherwise use `UNKNOWN` and mark operation unresolved.
- “the client” is neither a named PERSON nor a named GROUP.

### Example 16 — chronology is not dependency

Text: “After lunch, send the report.”

- TASK “send the report”; TEMPORAL “After lunch”; ARTIFACT “report.”
- A `SCHEDULED_ON` relation may be appropriate.
- Do not create `DEPENDS_ON`: lunch is a temporal anchor, not a necessary prerequisite.

### Example 17 — genuine task-to-task dependency

Text: “After Alice approves the draft, Bob will send the final report.”

- TASK 1 “approves the draft,” assigned to Alice.
- TASK 2 “send the final report,” assigned to Bob.
- Add `DEPENDS_ON(TASK 2, TASK 1)` because approval is the required gate for sending.
- Store the complete conditional clause as exact relation evidence if a smaller span loses the relation.

### Example 18 — dependency on an event

Text: “Release the funds once regulatory approval is received.”

- TASK “Release the funds.”
- EVENT “regulatory approval is received.”
- Add `DEPENDS_ON(release funds, approval received)`.
- “once” contributes evidence, but the contingency—not the word alone—licenses the edge.

### Example 19 — “before” used only as a deadline

Text: “Call Bob before 3 PM.”

- TASK “Call Bob”; PERSON “Bob”; TEMPORAL “before 3 PM.”
- Add `DUE_ON`, not `DEPENDS_ON`.

### Example 20 — “after” with no task dependency

Text: “We will have drinks after work.”

- No TASK unless the project explicitly treats social plans as actionable work, which Text2Task does not by default.
- “after work” is temporal language, not prerequisite evidence.

### Example 21 — pronoun-only owner

Text: “She will send the report.”

- TASK “send the report”; ARTIFACT “report.”
- Do not create PERSON “She” or an `ASSIGNED_TO` edge.
- Mark ASSIGNEE unresolved, TEMPORAL missing, and `ambiguous=true`.

### Example 22 — named antecedent plus pronoun

Text: “Alice reviewed the draft. She will send it tomorrow.”

- PERSON “Alice”; EVENT “reviewed”; ARTIFACT “draft”; TASK “send it”; TEMPORAL “tomorrow.”
- Add the temporal relation.
- Do not add `REFERS_TO(She, Alice)` or `REFERS_TO(it, draft)` in v1. Do not infer `ASSIGNED_TO` through the pronoun-resolution shortcut; mark it unresolved.

### Example 23 — overlapping TASK and ARTIFACT

Text: “Please update the quarterly report.”

- TASK “update the quarterly report.”
- ARTIFACT “quarterly report.”
- The spans overlap by design. Do not shorten the TASK to “update” merely to avoid overlap.

### Example 24 — named versus generic collective

Text: “Legal Operations will review it; everyone should wait.”

- GROUP “Legal Operations.”
- “everyone” is not a GROUP because it is not a named collective.
- The task object “review it” is valid, but artifact resolution is deferred.

### Example 25 — vague deadline

Text: “Please send the summary soon.”

- TASK “send the summary”; ARTIFACT “summary”; TEMPORAL “soon.”
- Add `DUE_ON` because “soon” directly constrains completion, but set task and relation ambiguity to true.
- Do not normalize “soon” to a date.

### Example 26 — missing owner and date

Text: “The contract needs review.”

- Annotate TASK “needs review” only if the context makes this an actual request or planned work rather than a factual observation.
- ARTIFACT “contract.”
- With no owner or temporal expression, mark both ASSIGNEE and TEMPORAL missing.
- If context does not establish intended action, annotate no TASK.

### Example 27 — no actionable task

Text: “Thanks for the update. The figures look correct.”

- No TASK.
- ARTIFACT or EVENT labels are optional only if relevant to another task or prerequisite; do not manufacture a graph to avoid an empty annotation.

### Example 28 — inferred relation with exact evidence

Text: “The signed form should go to Maria.”

- If “go to Maria” clearly assigns delivery responsibility or destination in the project context, an inferred relation may be considered, but the inference must be documented and evidence must be the exact span “The signed form should go to Maria.”
- If it is unclear whether Maria is the owner or recipient, do not force `ASSIGNED_TO`; mark ASSIGNEE unresolved.

### Example 29 — resolved cross-email identity

Email 1: “Alice, revise the tariff filing.” Email 2: “The tariff filing revision is complete.”

- If both turns clearly refer to the same revision, assign the same `thread-task:<thread>:<task>` identifier.
- First mention: `operation=UPDATE`, `status=PENDING`.
- Completion mention: `operation=COMPLETE`, `status=COMPLETED`.
- The shared ID preserves identity; it does not make a new cross-record relation edge.

### Example 30 — unresolved cross-email identity

Email 1 mentions “the monthly report.” A later email says “the report is done,” but the thread also discusses a risk report.

- Do not choose one by intuition.
- Set `identity_status=UNRESOLVED`, keep `thread_task_id=null`, add `CROSS_EMAIL_IDENTITY`, set `ambiguous=true`, and explain the competing artifacts in `notes`.

### Example 31 — `NONE` candidate pair

Text: “Alice reviewed the report on Monday.” Suppose TASK “reviewed the report,” PERSON “Alice,” ARTIFACT “report,” and TEMPORAL “Monday” are present for a supported thread update.

- A task/person candidate may be positive if ownership is supported.
- A TASK→ARTIFACT pair has no relation label in the v1 graph. If generated as a relation-classification candidate, label it `NONE`; keep evidence and explicitness null.
- Never copy that `NONE` pair into `relations`.

### Example 32 — duration

Text: “Monitor the queue for two hours.”

- TASK “Monitor the queue”; TEMPORAL “for two hours.”
- Use `SCHEDULED_ON` if the duration describes planned execution. Do not reinterpret it as a deadline.

## Machine validation

Use `src.annotation.validators` to validate both unannotated input records and pilot annotations:

```python
from src.annotation.validators import assert_valid_jsonl, assert_valid_record

assert_valid_jsonl("data/candidates/dev.jsonl")
assert_valid_record(pilot_record, require_annotations=True)
```

Validation checks JSON structure, exact substrings, offset bounds, unique IDs, endpoint types, evidence spans, task attributes, missing/unresolved markers, `NONE` placement, deferred references, and cross-email identity consistency.

## Pilot review gate

Before bulk labeling:

1. Select a small stratified pilot containing direct requests, no-task emails, pronouns, multiple tasks, deadline/schedule contrasts, cancellation, negation, and dependencies.
2. Have at least two reviewers independently annotate it.
3. Review span disagreements separately from entity, attribute, relation, and cross-email identity disagreements.
4. Adjudicate every dependency and inferred relation.
5. Revise the schema or guidelines if recurring cases cannot be represented consistently.
6. Revalidate all pilot JSON after any schema change.
7. Begin bulk labeling only after the pilot is accepted and schema versioning is frozen.
