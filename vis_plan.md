# Text2Task — Visualization Implementation Plan

**Project:** Text2Task: Neural Action-Item Extraction and Dependency-Aware Task Graph Generation  
**Document:** `vis_plan.md`  
**Purpose:** Implementation plan for a clear, interactive multi-user chat and task-dependency simulation UI.

## 1. Product vision

Build a **simulated workplace messenger** where a presenter can switch between team members, send messages on their behalf, and see Text2Task convert conversations into **per-user to-do lists and cross-user dependencies**. The interface must make the NLP pipeline observable: which message produced which task, who was assigned, why a deadline or dependency was inferred, and whether an uncertain prediction needs review.

**Primary demo journey:** Riya assigns Anushree a dataset-preparation task → switch to Anushree to see it in her to-dos → Anushree says Bianca can train the model *after* the dataset is prepared → observe a dependent task appear for Bianca and a directed edge in the graph → Anushree reports completion → the dependent task becomes unblocked.

**Design principle:** The chat and tasks should feel like a coherent application, not a dump of NLP predictions. Keep the visualization uncluttered, with explanations accessible on demand.

### Non-negotiable behavior

- User switching changes **the active persona and personal perspective**, not the workspace's underlying chat or task state.
- An assignment addressed to someone else appears in **their** to-do list, not automatically in the sender's.
- The **same task persists** across follow-up messages. Reconciliation should update rather than duplicate where identity is sufficiently clear.
- A dependency arrow always points **prerequisite → dependent task**. Mere message order does not establish a dependency.
- Every suggested task, relationship, or update has a **source message and evidence**.
- Live model output, heuristic fallback, scripted demo output, and human corrections must be **visibly distinguishable**. Never silently present scripted outputs as neural predictions.
- Do not claim that the entity model alone predicts ownership, dependencies, or reconciliation. Those capabilities need separate components or explicitly marked rules/manual edits.

## 2. Audience and success criteria

**Audience:** College ML project evaluator, developer, and presenter.  
**Key user stories:**

1. As a presenter, I can switch users and simulate a realistic conversation without registering accounts.
2. As a simulated team member, I can see only my assigned tasks by default, with an option to view all tasks.
3. As an evaluator, I can select a message and inspect the model's detected entities, relation evidence, and resulting task changes.
4. As a team member, I can review, accept, edit, or dismiss a low-confidence task/update.
5. As an evaluator, I can watch the dependency graph evolve step by step and inspect blockers.
6. As a presenter, I can replay deterministic scenarios or enter live messages and compare behavior.

**MVP acceptance checks:**
- Switching active user changes the task filter and sender identity while retaining shared chat state.
- A clear assigned task is proposed or created in the intended user's list after message processing.
- A follow-up completion or deadline-change message updates one existing task rather than duplicating it when resolution is unambiguous.
- A supported dependency creates a directed, source-traceable edge and blocked state.
- Clicking a task reveals its origin and later update history.
- Reset and replay produce deterministic scenario state.
- The interface exposes errors, uncertainty, or unavailable models rather than inventing outputs.

## 3. Information architecture

### Main views

| View | Primary job | Main content |
|---|---|---|
| **Workspace** | Main interactive simulation | Team chat, current user's to-dos, compact dependency overview |
| **Dependency Explorer** | Understand the workflow | Large interactive directed task graph, owner/status filters, edge details |
| **Activity / History** | Explain state changes | Timeline of message → extraction → proposed or applied task changes |
| **Model Inspector** | Demonstrate ML mechanics | Entity highlights, candidate relations, confidence/uncertainty, raw vs reviewed results |
| **Scenario Library** | Repeat a reliable demo | Load, play one message, autoplay if desired, reset, compare scenarios |

**Navigation:** Workspace and Dependency Explorer are primary tabs. Scenario Library is a button/drawer near the chat header. Model Inspector opens as a **contextual right drawer** from any message, suggestion, task, or graph edge. History is accessible from task details and a workspace activity toggle.

### Desktop layout (recommended)

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Text2Task    [Workspace] [Dependencies]      Scenario ▼   [Demo / Live]     │
│ Team: ML Project                             Active user: [Riya ▼]          │
├───────────────────────┬──────────────────────┬───────────────────────────────┤
│ CHAT                  │ MY TASKS             │ DEPENDENCY PREVIEW            │
│                       │ [Mine | All users]   │                               │
│ Riya: Prepare data... │ ▢ Prepare dataset    │ [Prepare data]                │
│ Anushree: I'll do it │   Anushree · Thurs   │       ↓                       │
│ ...                   │ ▢ Train model        │ [Train model]                 │
│                       │   Bianca · Blocked   │                               │
│ [Message as Riya...]  │ [Review queue 2]     │ [Open full explorer]          │
├───────────────────────┴──────────────────────┴───────────────────────────────┤
│ Scenario:  2 / 5 messages   [Previous] [Next] [Reset]   [Activity]           │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Responsiveness:** On narrow screens, switch to Chat / Tasks / Graph segmented tabs; keep the current persona and scenario controls accessible. The full graph should retain pan and zoom.

## 4. Visual style and interaction rules

- **Aesthetic:** Modern, understated collaboration software; neutral surfaces, generous spacing, subtle separators, consistent radii.
- **Hierarchy:** Chat is the primary narrative; tasks are the primary output; graph is the causal explanation. Avoid four dashboards competing for attention.
- **Color:** Use a consistent accessible accent per user for avatars and graph nodes; use separate status indicators (completed, blocked, proposed, overdue). Never encode status by color alone.
- **Type:** Clear headings, compact metadata, readable message text. Avoid dense metric panels on the main screen.
- **Animation:** Gentle task-card insertion, graph edge reveal, and short highlight of affected items. Respect reduced-motion preferences.
- **Evidence-first interaction:** Selecting a task highlights its source message; selecting an edge shows the statement establishing the prerequisite.
- **Accessible controls:** Keyboard focus, descriptive buttons, tooltips for unfamiliar statuses, and sufficient color contrast.

## 5. Core features

### 5.1 Multi-user mock chat

**Components:** `WorkspaceHeader`, `UserSwitcher`, `ChatPanel`, `MessageBubble`, `MessageComposer`, `ScenarioControls`.

- Preload three personas: **Riya (Project Lead), Anushree (Data Engineer), Bianca (ML Engineer)**. Allow editing display names and optionally adding a fourth user.
- One shared conversation is sufficient for MVP; avoid implementing production messaging, authentication, notifications, or permissions.
- Composer sends as selected persona. Support messages addressed to one or several participants.
- Each message shows sender, timestamp, processing status, and a compact “N changes suggested” chip when relevant.
- Clicking a message opens the Model Inspector and highlights extracted spans in the original message.
- Support **Reset workspace** and **Reset scenario** separately.
- Optional: conversation threads/channels after MVP, not required initially.

### 5.2 Per-user to-do lists

**Components:** `TaskPanel`, `TaskCard`, `AssigneeFilter`, `TaskDetails`, `ReviewQueue`.

Each task card shows:
- Normalized action title
- Assignee/avatar
- Deadline or “No confirmed due date”
- Status: Proposed / To Do / In Progress / Blocked / Done / Canceled
- Dependency count or blocked-by preview
- Link back to the originating message

**Behaviors:**
- Switch active user → “My Tasks” filters by that user.
- Toggle “All users” to see the team board, grouped by assignee or status.
- Clicking a task opens details with source message, history, raw extraction, and editable fields.
- Mark done, reopen, and correct assignee/deadline manually; record these actions as user edits, not model predictions.
- Do not automatically assign an ambiguous “you” when message context is insufficient.

### 5.3 Suggested changes and review queue

A **suggestion** is different from an **accepted task**. The backend may propose a new task, task update, dependency, or dismissal.

Review card actions: **Accept**, **Edit**, **Dismiss**. Include a one-line reason and evidence quote. The suggestion can be marked `needs_review` without inventing a meaningful confidence probability.

**Modes:**
- **Review mode (default):** Every model-derived change requires confirmation. Reliable for early-stage model demos.
- **Automatic mode (optional):** Only explicitly configured, validated high-confidence categories auto-apply; uncertain changes remain in review. Do not treat uncalibrated model softmax as a trustworthy probability threshold.

### 5.4 Interactive dependency graph

**Library recommendation:** React Flow (`@xyflow/react`) for graph editing/interaction; `dagre` or ELK for layout; NetworkX on the backend for directed graph checks.

**Nodes:** Task title, owner, due date, status; optional user-color border.  
**Edges:** `prerequisite_task_id → dependent_task_id`. Edge details include source message, original phrase, extractor origin, and review state.

**Interactions:**
- Auto-layout from left to right or top to bottom; fit-to-view and zoom.
- Select node → highlight corresponding task, owner, and source message.
- Select edge → show prerequisite evidence and which task it blocks.
- Filter by assignee, state, or scenario step.
- Highlight **blocked** nodes if any accepted prerequisite is incomplete.
- Detect potential cycles; show warning and hold invalid edge for review rather than silently dropping it.
- Never create dependency edges from simple chronological ordering.

**Graph legend:** User colors represent owners. Solid edge = accepted relation; dashed edge = suggested/unconfirmed relation. Status is indicated with a label/icon, not only color.

### 5.5 AI Inspector

**Open from:** message bubble, task card, graph node, edge, suggestion.

**Panels (progressive disclosure):**
1. **Message + entity highlights:** TASK / PERSON / GROUP / TEMPORAL / EVENT / ARTIFACT; toggle predicted versus reviewed labels if both exist.
2. **Relationships:** ASSIGNED_TO, DUE_ON, SCHEDULED_ON, DEPENDS_ON, with supporting message text.
3. **Resolution:** raw temporal phrase → normalized date, or unresolved when reference timestamp is absent.
4. **Task reconciliation:** CREATE, PROPOSE_UPDATE, CONFIRM_UPDATE, COMPLETE, CANCEL, NO_CHANGE, or NEEDS_REVIEW, with matching task candidate and reason.
5. **Provenance:** model version, pipeline mode, run ID, and whether a result was neural, heuristic, scripted, or human-corrected.

Do not present attention weights or logits as a faithful natural-language explanation of why the model reached a conclusion. Use **evidence spans and explicit rule traces** instead.

## 6. Automatic reconciliation of follow-up messages

### What needs to happen

A new message may describe a new task, refer back to an existing task, change its owner/date, report completion, cancel it, or propose a change that has not been confirmed.

**Reconciliation pipeline:**

```text
New message
  → Entity extraction
  → Relation candidates and temporal parsing
  → Candidate existing-task retrieval (same team/thread, title/assignee/context)
  → Task-matching score + evidence
  → Proposed operation
  → Validate status/date/dependency consistency
  → Auto-apply ONLY if permitted; otherwise ask for review
  → Persist event/history and update task lists + graph
```

**Candidate-matching signals:** normalized action/object overlap, explicit task identifiers, assignee context, referenced message, recency within the same thread, deadline context, and clear completion/change verbs. These are heuristics until a trained matcher exists; expose the actual method in the Inspector.

**Safe matching rules:**
- One clear task referent → propose an update to that task.
- Multiple plausible matches → ask which task is intended.
- No convincing match → create a proposed new task or mark unresolved; never silently overwrite an unrelated task.
- A statement that merely mentions a past action → no new task unless it expresses a new actionable request/commitment.
- “Could we move it to Friday?” → proposed change, **not** confirmed deadline update.
- “Yes, Friday works” → confirm the pending proposed change only when context resolves unambiguously.
- “I finished the dataset” → completion update only if a matching dataset task exists.
- Corrections and overrides must remain reversible in task history.

### Suggested event-sourced operations

```text
CREATE_TASK
UPDATE_ASSIGNEE
PROPOSE_DUE_DATE_CHANGE
CONFIRM_DUE_DATE_CHANGE
UPDATE_STATUS
COMPLETE_TASK
CANCEL_TASK
ADD_DEPENDENCY
REMOVE_DEPENDENCY
DISMISS_SUGGESTION
MANUAL_CORRECTION
```

Each accepted operation creates an immutable history entry linking `message_id`, `task_id`, `actor`, `operation`, `before`, `after`, `source` and `timestamp`.

## 7. Scenario library and expected behavior

Use **step-through playback** to make the project easy to demonstrate. Each fixture must contain messages, expected structured outputs, and expected state changes. Present fixtures as **scripted expectations**, not real model predictions. In Live mode, show actual outputs and differences.

### Scenario A — Simple assignment (MVP)

**Users:** Riya, Anushree, Bianca.

| Step | Sender | Message | Expected behavior |
|---|---|---|---|
| 1 | Riya | “Anushree, please prepare the cleaned dataset by Thursday.” | Propose **Prepare cleaned dataset**, assignee Anushree, due Thursday if a reference date is available; otherwise keep relative date unresolved. |
| 2 | Anushree | “Sure, I'll take care of the dataset.” | Recognize commitment; resolve to existing dataset task, no duplicate. |
| 3 | Riya | “Bianca, please train the entity model once Anushree finishes the dataset.” | Propose **Train entity model**, assignee Bianca; add prerequisite **Prepare cleaned dataset → Train entity model** after confirmation. |
| 4 | Anushree | “The cleaned dataset is ready.” | Propose/confirm completion of Anushree's task; update Bianca's blocked status when edge is accepted. |
| 5 | Bianca | “I'll begin training now.” | Recognize progress/update on existing task; do not create duplicate. |

**Visual demo moments:** switch Riya → Anushree → Bianca; show tasks under the correct owner; reveal graph edge; complete upstream task; show unblocked state; open source-evidence drawer.

### Scenario B — Deadline change

1. Riya: “Bianca, send me the model report by Thursday.” → New assigned task.
2. Bianca: “Could we move the deadline to Friday?” → **Proposed change**, not yet applied.
3. Riya: “Friday is fine.” → Confirm same task's deadline; one task record with history.

### Scenario C — Ambiguity

1. Riya: “Can someone review the slides?” → Unassigned suggestion / clarification.
2. Anushree: “I can review them.” → Link commitment to the existing suggestion, subject to review.
3. A separate slide-review task exists → display match options instead of silently guessing.

### Scenario D — Non-actionable messages

- “The server went down yesterday.” → historical event, no new to-do.
- “The request was rejected.” → status information, not automatically a new task.
- “Please investigate why the server went down.” → actionable task.

### Scenario E — Dependency conflict

Create A → B, then suggest B → A. Show cycle warning, hold the new dependency for review, and keep the accepted graph valid.

**Scenario controls:** Load Scenario, Previous Step (rebuild state deterministically), Next Message, Play All (optional), Reset, Demo/Live mode toggle. Show `Step X of Y`.

## 8. Architecture and data contracts

### Recommended stack

| Layer | Recommendation | Purpose |
|---|---|---|
| Frontend | React + TypeScript + Vite | Responsive single-page app |
| Styling | Tailwind CSS + accessible component primitives | Consistent UI, fast implementation |
| Graph | `@xyflow/react` + dagre/ELK | Directed interactive dependency visualization |
| Backend | FastAPI | Chat simulation APIs, orchestration, review endpoints |
| ML | Existing Python Text2Task code | Entity extraction and any genuinely implemented relation models |
| Graph logic | NetworkX | DAG checks, predecessors, blocked states |
| Persistence | SQLite | Users, messages, tasks, suggestions, edges, history |

**Do not replace existing ML/backend modules.** Add a thin adapter that calls current inference scripts/functions. If relation extraction or reconciliation is not ready, expose deterministic heuristics or manual review as explicitly labeled fallbacks.

### Minimum entities

```ts
type SourceKind = "model" | "rule" | "scripted" | "human";
type TaskStatus = "proposed" | "todo" | "in_progress" | "blocked" | "done" | "canceled";

type User = { id: string; name: string; role?: string; color: string };
type Message = { id: string; senderId: string; text: string; createdAt: string; scenarioStep?: number };
type Task = {
  id: string;
  title: string;
  assigneeId: string | null;
  dueAt: string | null;
  dueText?: string | null;
  status: TaskStatus;
  createdFromMessageId: string;
  version: number;
};
type Dependency = {
  id: string;
  prerequisiteTaskId: string;
  dependentTaskId: string;
  sourceMessageId: string;
  accepted: boolean;
  sourceKind: SourceKind;
  evidence: string;
};
type Suggestion = {
  id: string;
  messageId: string;
  kind: "create_task" | "update_task" | "add_dependency" | "clarification";
  proposedChange: Record<string, unknown>;
  status: "pending" | "accepted" | "edited" | "dismissed";
  sourceKind: SourceKind;
  evidence: string;
};
type TaskHistory = {
  id: string;
  taskId: string;
  messageId: string | null;
  operation: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  actorId: string | null;
  sourceKind: SourceKind;
  timestamp: string;
};
```

Additional extraction results should store span offsets, entity type, predicted label, model version and provenance. Keep raw text and extracted spans aligned to the same exact message text.

### API sketch

```text
GET    /api/users
GET    /api/workspace
POST   /api/messages                 # Append and analyze a simulated message
GET    /api/tasks?assignee_id=...
PATCH  /api/tasks/{id}              # Manual changes, recorded in history
GET    /api/dependencies
GET    /api/messages/{id}/analysis
GET    /api/suggestions
POST   /api/suggestions/{id}/accept
POST   /api/suggestions/{id}/dismiss
GET    /api/tasks/{id}/history
POST   /api/scenarios/{id}/load
POST   /api/scenarios/{id}/step
POST   /api/scenarios/reset
GET    /api/system/capabilities       # Which models and fallbacks are actually ready
```

For a small local demo, request/response updates plus frontend state refresh are enough. WebSockets are optional, not a prerequisite.

## 9. Build plan in five implementation phases

### Phase 1 — Polished simulation shell

**Implement:** App layout, mock personas, shared chat, user switcher, message composer, scenario library and deterministic playback. Use local fixture data initially.  
**Done when:** Presenter can send as different users, load a scenario, step through it, reset, and replay without inconsistent state.

### Phase 2 — Task panels and review interactions

**Implement:** Per-user task views, task cards, all-users filter, suggested changes queue, task details, source-message linking, accept/edit/dismiss.  
**Done when:** Scenario assignments appear under the correct user, uncertain cases require review, and edits update state visibly.

### Phase 3 — Dependency Explorer

**Implement:** React Flow nodes/edges, auto-layout, owner/status filters, blocked-state computation, cycle validation, node/edge selection.  
**Done when:** Scenario A visibly creates a prerequisite edge, upstream completion unblocks a downstream task, and an attempted cycle is flagged.

### Phase 4 — Connect real Text2Task inference

**Implement:** FastAPI adapter to actual entity model; relation and temporal modules if available; consistent provenance and error handling; Model Inspector with span highlights and evidence. Support scripted fixtures separately from real predictions.  
**Done when:** Live messages produce *actual* extracted spans and available downstream results, including visible failures and unanswered fields. Do not hardcode successful outputs in Live mode.

### Phase 5 — Reconciliation, history, and evaluation polish

**Implement:** Candidate task matching, explicit operation proposals, versioned changes, task history, deadline change and ambiguity scenarios, compact evaluation panel using genuine recorded metrics.  
**Done when:** A follow-up references and updates a prior task, no duplicate appears when matching is clear, ambiguous matching asks for review, and change history is inspectable.

## 10. Guardrails, tests, and failure states

**Must test:**

- User switch does not create or remove underlying messages/tasks.
- Source IDs and evidence remain attached after a task update.
- Repeated messages do not automatically create duplicate tasks when a confirmed match exists.
- Proposed deadline change does not alter due date until confirmed.
- “Yesterday's failure” does not become a new to-do without an actionable request.
- Dependency arrows follow prerequisite → dependent direction.
- Blocked state updates when prerequisites are completed or reopened.
- Cycle detection prevents accepting cyclic edges.
- Graph supports zero, one, or many nodes without UI errors.
- Scenario reset restores original state exactly.
- Live mode fails visibly when model unavailable; scripted mode never masquerades as model output.
- Human edits and LLM labels retain provenance; SILVER predictions aren't described as GOLD.

**Empty/error states:** “No tasks yet,” “No confirmed dependencies,” “Assignee unresolved,” “Date needs a reference timestamp,” “Suggested change needs review,” “Model unavailable,” “Inference failed — retry.”

## 11. Recommended MVP cut line

**Essential now:**
1. Shared mock chat and active-user switcher.
2. Per-user to-do cards with source-message links.
3. Scenario A step playback.
4. Review queue (accept/edit/dismiss).
5. Directed dependency graph with blocked state.
6. Visible Demo vs Live mode and actual-model inspector when available.

**If time permits:** task reconciliation history, deadline-change scenario, timeline, compact evaluation dashboard, richer graph animations.

**Defer:** authentication, real multi-device messaging, notifications, production access controls, full calendar integrations, critical-path optimization, sophisticated conversational coreference training.

## 12. Final presentation script (3–5 minutes)

1. **Context (20 seconds):** “Workplace chat hides action items and implicit handoffs. Text2Task turns messages into linked tasks.”
2. **Assign (40 seconds):** Riya asks Anushree to prepare the dataset. Show highlighted TASK/PERSON/TEMPORAL and the task proposal; accept it.
3. **Switch users (30 seconds):** Switch to Anushree; the task appears under My Tasks. Switch back to Riya and show team overview.
4. **Create dependency (50 seconds):** Ask Bianca to train once the data is ready. Approve relation. Open graph and show Anushree's task blocking Bianca's.
5. **Resolve blocker (40 seconds):** Anushree says the dataset is ready. Resolve the existing task, mark complete, and show the graph update.
6. **Inspect intelligence (40 seconds):** Click a task/edge to show source message, extracted spans, relation evidence, and which components were model- or rule-derived.
7. **Limitations (20 seconds):** Explain that uncertain matches require review and that evaluation results are presented with truthful GOLD/SILVER provenance.

## 13. Definition of done

The visualization is complete when a reviewer can **watch a conversation create tasks for different users, observe a real prerequisite block another task, and inspect why each change happened**—without reading raw JSON, losing track of who's speaking, or mistaking scripted examples for actual model accuracy.
