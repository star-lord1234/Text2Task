import type { Analysis, GraphData, GraphEdge, GraphNode, MessageView, Participant, Suggestion, TaskDetail, TaskView, TemporalValue } from '../api/types'

export const people: Participant[] = [
  { id: 'riya', name: 'Riya', role: 'Project Lead', color: '#6c5ce7' },
  { id: 'anushree', name: 'Anushree', role: 'Data Engineer', color: '#00a38c' },
  { id: 'bianca', name: 'Bianca', role: 'ML Engineer', color: '#e17055' },
]

export const resolved = (value: string, raw = value): TemporalValue => ({ raw, status: 'RESOLVED', granularity: 'DATE', start: value, end: value, value, assumptions: [] })

export const task = (over: Partial<TaskView> = {}): TaskView => ({
  id: 'T-1', title: 'prepare the cleaned dataset', owner_id: 'anushree', lifecycle: 'open', derived_state: 'ready', ui_status: 'todo', blocked_by: [], cancelled_prereqs: [], root_blockers: [],
  due: resolved('2026-11-12', 'Thursday'), scheduled: null, version: 1, source_message_id: 'A-1', created_by: 'riya', thread_id: 'default', evidence_text: '', pending_changes: {},
  blocks_count: 0, blocked_by_count: 0, last_touched_message_id: 'A-1', ...over,
})

export const suggestion = (over: Partial<Suggestion> = {}): Suggestion => ({
  id: 'P-1', message_id: 'A-1', kind: 'create_task', operation: 'CREATE_TASK', task_id: null, field: '__create__', summary: 'Create task “prepare the cleaned dataset” — Anushree, due 2026-11-12',
  status: 'pending', needs_review: true, source_kind: 'scripted', provenance: { extraction: 'scripted', linking: 'scripted', reconciliation: 'rule (cue-based)', applied_by: null },
  evidence: { sentence: 'Anushree, please prepare the cleaned dataset by Thursday.' }, flags: [], note: '', before: null,
  after: { title: 'prepare the cleaned dataset', owner_id: 'anushree', due: resolved('2026-11-12', 'Thursday') }, base_version: null, needs_confirmation_from: [], unresolved: [],
  requires_referent: false, match: {}, must_accept_first: [], direct: false, resolved_by: null, resolution_note: null, created_at: null,
  reviewer_ids: ['anushree'], proposer_id: 'riya', ...over,
})

export const message = (over: Partial<MessageView> = {}): MessageView => ({
  id: 'A-1', sender_id: 'riya', recipient_ids: ['anushree'], text: 'Anushree, please prepare the cleaned dataset by Thursday.', created_at: '2026-11-11T09:30:00-06:00', mode: 'scripted',
  status: 'analysed', error: null, scenario_id: 'A', scenario_step: 1, thread_id: 'default', in_reply_to: null, proposals: [], pending_count: 0, applied_count: 0, no_change: [],
  provenance: {}, run_id: 'r-1', expected: null, matches_expectation: null, ...over,
})

const node = (over: Partial<GraphNode>): GraphNode => ({
  id: 'T-1', title: 'prepare the cleaned dataset', owner_id: 'anushree', status: 'open', derived_state: 'ready', blocked_by: [], cancelled_prereqs: [], root_blockers: [], due: '2026-11-12',
  due_status: 'RESOLVED', scheduled: null, layer: 0, source_message_id: 'A-1', thread_id: 'default', version: 1, ...over,
})
export const edge = (over: Partial<GraphEdge> = {}): GraphEdge => ({
  id: 'E-1', source: 'T-1', target: 'T-2', kind: 'accepted', status: 'accepted', evidence: 'once Anushree finishes the dataset', source_message_id: 'A-3', source_kind: 'rule', score: null,
  reason: '', warnings: [], redundant: false, dangling: false, ...over,
})
export const graph = (nodes: GraphNode[] = [node({}), node({ id: 'T-2', title: 'train the entity model', owner_id: 'bianca', derived_state: 'blocked', blocked_by: ['T-1'], layer: 1 })], edges: GraphEdge[] = [edge()]): GraphData => ({
  nodes, edges, meta: { schema: 'phase6-v1', workspace: 'default', acyclic: true, cycle: [], node_count: nodes.length, accepted_edges: edges.filter((e) => e.kind === 'accepted').length,
    proposed_edges: 0, held_edges: edges.filter((e) => e.kind === 'held').length, ready: [], blocked: [], needs_review: [] },
})
export { node as graphNode }

export const analysis = (over: Partial<Analysis> = {}): Analysis => ({
  message: message(), entities: [{ id: 'e1', type: 'PERSON', start: 0, end: 8, text: 'Anushree' }, { id: 'e2', type: 'TASK', start: 17, end: 44, text: 'prepare the cleaned dataset' }, { id: 'e3', type: 'TEMPORAL', start: 48, end: 56, text: 'Thursday' }],
  relations: [{ source_id: 'e2', target_id: 'e1', label: 'ASSIGNED_TO', score: null, provenance: 'scripted', model_version: 'scenario fixture', source_text: 'prepare the cleaned dataset', target_text: 'Anushree' }],
  no_link: [], candidates: [], refinement: null, proposals: [], provenance: { entities: 'scripted', relations: 'scripted', temporal: 'rule', identity: 'rule', reconciliation: 'rule (cue-based)' }, model_versions: {},
  error: null, run_id: 'r-1', duration_ms: 3.2, classes_supported: ['TASK', 'PERSON', 'TEMPORAL'], classes_not_produced: ['GROUP', 'EVENT', 'ARTIFACT'], score_note: 'Model scores are uncalibrated softmax values, not probabilities.', ...over,
})

export const taskDetail = (over: Partial<TaskDetail> = {}): TaskDetail => ({
  ...task(), source_message: message(), edges: [], provenance: {},
  history: [{ event_id: 1, task_id: 'T-1', proposal_id: 'P-1', message_id: 'A-1', actor: 'riya', operation: 'CREATE_TASK', field: '__create__', before: null, after: { title: 'prepare the cleaned dataset' }, timestamp: '2026-11-11T09:30:01-06:00', source_kind: 'scripted', note: '' }], ...over,
})
