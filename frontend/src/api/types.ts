// Shapes returned by the FastAPI views (src/api/views.py). Request bodies come from the generated schema (pnpm gen:types).
export type SourceKind = 'neural' | 'rule' | 'scripted' | 'human'
export type Mode = 'scripted' | 'live'

export type Participant = { id: string; name: string; role: string | null; color: string }

export type TemporalValue = {
  raw: string
  status: string
  granularity: string | null
  start: string | null
  end: string | null
  value: string | null
  part_of_day?: string | null
  assumptions: string[]
  rule_id?: string | null
  in_past?: boolean | null
  candidates?: Array<Record<string, unknown>>
  anchor_used?: string | null
}

export type Flag = { code: string; severity: 'info' | 'warn' | 'block'; field: string; message: string; question?: string | null; evidence?: string | null }

export type ProposalBrief = { id: string; operation: string; status: string; summary: string; flag_codes: string[]; warn: boolean; task_id: string | null }

export type MessageView = {
  id: string; sender_id: string; recipient_ids: string[]; text: string; created_at: string; mode: Mode
  status: 'received' | 'analysed' | 'analysis_failed' | 'no_extraction'; error: string | null
  scenario_id: string | null; scenario_step: number | null; thread_id: string; in_reply_to: string | null
  proposals: ProposalBrief[]; pending_count: number; applied_count: number; no_change: string[]
  provenance: Record<string, string>; run_id: string | null
  expected: { operations: string[]; note: string } | null; matches_expectation: boolean | null
}

export type Suggestion = {
  id: string; message_id: string; kind: 'create_task' | 'update_task' | 'add_dependency' | 'clarification' | 'no_change'; operation: string
  task_id: string | null; field: string | null; summary: string; status: string; needs_review: boolean; source_kind: SourceKind
  provenance: { extraction: string; linking: string; reconciliation: string; applied_by: string | null }
  evidence: { sentence?: string; start?: number; end?: number; message_id?: string }
  flags: Flag[]; note: string; before: unknown; after: unknown; base_version: number | null
  needs_confirmation_from: string[]; unresolved: string[]; requires_referent: boolean
  match: { outcome?: string; ranked?: Array<{ task_id: string; score: number; raw_score?: number; signals: Record<string, number> }>; reason?: string }
  must_accept_first: Array<{ proposal_id: string; status: string; summary: string | null }>; direct: boolean
  resolved_by: string | null; resolution_note: string | null; created_at: string | null
  /** Who may accept it: the person it lands on (assignee, owner of the affected task, …). Empty = any teammate. */
  reviewer_ids: string[]; proposer_id: string | null
}

export type UiStatus = 'todo' | 'in_progress' | 'blocked' | 'done' | 'canceled' | 'needs_review'
export type TaskView = {
  id: string; title: string; owner_id: string | null; lifecycle: string; derived_state: string; ui_status: UiStatus
  blocked_by: string[]; cancelled_prereqs: string[]; root_blockers: string[]
  due: TemporalValue | null; scheduled: TemporalValue | null; version: number
  source_message_id: string | null; created_by: string | null; thread_id: string; evidence_text: string
  pending_changes: Record<string, { value: TemporalValue; proposer_id: string | null; proposal_id: string | null; needs_confirmation_from: string[] }>
  blocks_count: number; blocked_by_count: number; last_touched_message_id: string | null
}

export type HistoryEvent = {
  event_id: number; task_id: string; proposal_id: string | null; message_id: string | null; actor: string | null; operation: string
  field: string; before: unknown; after: unknown; timestamp: string; source_kind: SourceKind; note: string
}

export type GraphNode = {
  id: string; title: string; owner_id: string | null; status: string; derived_state: string; blocked_by: string[]; cancelled_prereqs: string[]
  root_blockers: string[]; due: string | null; due_status: string | null; scheduled: string | null; layer: number | null
  source_message_id: string | null; thread_id: string; version: number
}
export type GraphEdge = {
  id: string; source: string; target: string; kind: 'accepted' | 'proposed' | 'held'; status: string; evidence: string
  source_message_id: string | null; source_kind: string; score: number | null; reason: string
  warnings: Array<{ code: string; severity: string; message: string }>; redundant: boolean; dangling: boolean
}
export type GraphMeta = {
  schema: string; workspace: string; acyclic: boolean; cycle: string[]; node_count: number; accepted_edges: number; proposed_edges: number
  held_edges: number; ready: string[]; blocked: string[]; needs_review: string[]
}
export type GraphData = { nodes: GraphNode[]; edges: GraphEdge[]; meta: GraphMeta; snapshot_step?: number }

export type ModelInfo = {
  name: string; status: string; available: boolean; error: string | null; provisional: boolean; provenance: string
  device?: string | null; version?: string | null; classes?: string[]; labels?: string[]
}
export type Capabilities = {
  entity_model: ModelInfo; relation_model: ModelInfo
  rule_fallback: { available: boolean; enabled: boolean; covers: string[]; note: string }
  rule_dependency_linker: { enabled: boolean; note: string }
  pipeline: { preset: string; config: Record<string, unknown>; presets: Array<{ name: string; note: string; config: Record<string, unknown> }> }
  modes: { scripted: boolean; live: boolean; live_reason: string | null }
  components: Record<string, string>
}

export type ScenarioState = {
  scenario_id: string | null; step: number; total: number | null; title: string | null; label: string
  next_message: { sender: string; text: string } | null
}
export type ScenarioInfo = { id: string; title: string; description: string; steps: number; timezone: string | null }

export type Settings = { timezone: string; allow_rule_fallback: boolean; rule_dependency_linker: boolean; pipeline_preset: string; refine_overrides: Record<string, boolean> }

export type Workspace = {
  participants: Participant[]; messages: MessageView[]; tasks: TaskView[]; suggestions: Suggestion[]; settings: Settings
  scenario: ScenarioState; graph_meta: GraphMeta; capabilities: Capabilities
}

export type Origin = 'neural' | 'refined' | 'rule'
export type RefinementOp = { op: string; from?: string | string[]; to?: string; rule?: string }
export type Entity = {
  id: string; type: 'TASK' | 'PERSON' | 'TEMPORAL'; start: number; end: number; text: string; confidence?: number | null
  /** Phase 7.5: where this span came from. Absent for scripted spans and for runs made before refinement existed. */
  origin?: Origin; refinement?: RefinementOp[]; neural_ids?: string[]; grammar?: { evidence: string; verb: string; phrase: string }
}
export type Relation = {
  source_id: string; target_id: string; label: string; score: number | null; provenance: SourceKind; model_version?: string | null
  source_text?: string | null; target_text?: string | null; evidence_text?: string; rule?: string; cue?: string
}
export type RefinementRecord = {
  version: string; config: Record<string, unknown> & { preset: string }
  raw_entities: Entity[]; entities: Entity[]; rule_relations: Relation[]; raw_relations: Relation[] | null
  relation_edits: Array<Record<string, string | number | null>>; clause_hints: Array<Record<string, any>>; clause_dependencies: Array<Record<string, any>>
  imperative_ids: string[]; trace: Array<Record<string, any>>
}
export type Analysis = {
  message: MessageView; entities: Entity[] | null; relations: Relation[]; no_link: Array<Record<string, unknown>> | null
  candidates: Array<Record<string, any>> | null; refinement: RefinementRecord | null; proposals: Suggestion[]; provenance: Record<string, string>; model_versions: Record<string, string>
  error: string | null; run_id: string | null; duration_ms: number | null; classes_supported: string[]; classes_not_produced: string[]; score_note: string
}
export type TaskDetail = TaskView & {
  source_message: MessageView | null; history: HistoryEvent[]; provenance: Record<string, unknown>
  edges: Array<{ id: string; prerequisite: string; dependent: string; kind: string; evidence: string; source_message_id: string | null; source_kind: string; reason: string }>
}
export type Impact = { became_ready: string[]; became_blocked: string[]; became_review: string[]; became_done: string[]; became_cancelled: string[]; changed: Record<string, [string, string]> }

export type Prf = { precision?: number; recall?: number; f1?: number; support?: number }
export type PhaseReport = { id: string; title: string; available: boolean; provenance?: string; sections?: Record<string, Record<string, unknown>>; limitations?: string[] }
export type EvaluationData = {
  provenance: string; statement: string; sources: string[]; missing: string[]
  entities: {
    available: boolean; model?: string; metric?: string; overall?: Prf; per_type?: Record<string, Prf>; note?: string
    rule_baseline?: { name: string; split: string; rows: number; lenient_f1: number; strict_f1: number; per_type_lenient_f1: Record<string, number> }
    mailex_runs?: Array<{ run: string; lenient_f1: number; strict_f1: number; overlap_f1: number }>
  }
  relations: {
    available: boolean; model?: string; split?: string; pairs?: number; limitations?: string[]
    mode_a?: { neural: { per_label: Record<string, Prf>; micro_f1: number; macro_f1: number; none_false_positive_rate: number }; rule: { per_label: Record<string, Prf>; micro_f1: number; macro_f1: number }; bootstrap_95ci?: Record<string, unknown> }
    mode_b?: Record<string, { micro_f1: number | null; candidate_recall: number | null }>
  }
  phases: PhaseReport[]
}
