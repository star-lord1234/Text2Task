import type { Analysis, Entity, Relation } from '../../api/types'
import { ProvenanceChip } from '../../components/ProvenanceChip'

export const TYPE_STYLE: Record<string, string> = {
  TASK: 'bg-accent-bg text-accent border-accent/30', PERSON: 'bg-ok-bg text-ok border-ok/30', TEMPORAL: 'bg-warn-bg text-warn border-warn/30',
}
const STAGE_LABEL: Record<string, string> = {
  span_snap: 'Snap to word boundary', filter_invalid_tasks: 'Remove invalid task fragments', merge_adjacent: 'Merge adjacent spans', temporal_merge: 'Merge date/time pieces',
  temporal_detect: 'Detect missed dates', grammar_recovery: 'Recover action phrases and names', clause_dependencies: 'Clause-level dependencies',
}
const STAGE_FLAGS: Array<[string, string]> = [
  ['span_snap', 'Snap spans to word boundaries'], ['filter_invalid_tasks', 'Drop invalid task fragments'], ['merge_adjacent', 'Merge adjacent spans'],
  ['temporal_detect', 'Detect dates the model missed'], ['temporal_merge', 'Merge date/time/deadline pieces'], ['grammar_recovery', 'Grammar: recover action phrases and names'],
  ['clause_dependencies', 'Clause-level dependencies'], ['context_lifecycle', 'Lifecycle without a task span'], ['rule_dependency_linker', 'Explicit-cue dependency rule'],
]

/** A span without its own origin came from whatever produced the message's entities: scripted spans must never read as "neural". */
export const originOf = (e: Entity, fallback = 'neural'): string => e.origin ?? fallback
const fmt = (v: unknown) => (Array.isArray(v) ? v.map((x) => `“${x}”`).join(' + ') : v == null ? '' : `“${v}”`)

/** One sentence per refinement operation: what changed, and which rule did it. */
export function describeOp(e: Entity): string[] {
  return (e.refinement ?? []).map((r) => {
    const rule = r.rule ? ` (${r.rule})` : ''
    switch (r.op) {
      case 'snap_to_word': return `Extended ${fmt(r.from)} to the word boundary: ${fmt(r.to)}${rule}`
      case 'merge_adjacent': return `Merged ${fmt(r.from)} into ${fmt(r.to)}`
      case 'merge_temporal': return `Merged date/time pieces ${fmt(r.from)} into ${fmt(r.to)}${rule}`
      case 'detect_temporal': return `Detected by rule, not by the model${rule}`
      case 'extend_to_action_phrase': return `Completed ${fmt(r.from)} to the action phrase ${fmt(r.to)}${rule}`
      case 'recover_action_phrase': return `Recovered by the grammar chunker; the model found no span here${rule}`
      case 'roster_name': return `Recovered from the participant list${rule}`
      default: return `${r.op}${rule}`
    }
  })
}

/** Raw neural vs refined spans, side by side in one place. */
export function SpanView({ a, view }: { a: Analysis; view: 'refined' | 'raw' }) {
  const ref = a.refinement
  const ents = view === 'raw' && ref ? ref.raw_entities : a.entities ?? []
  return <Highlighted text={a.message.text} entities={ents} fallback={a.provenance.entities?.split(' ')[0]} />
}

export function Highlighted({ text, entities, fallback }: { text: string; entities: Entity[]; fallback?: string }) {
  const sorted = [...entities].sort((x, y) => x.start - y.start)
  const parts: Array<{ t: string; e?: Entity }> = []
  let i = 0
  for (const e of sorted) {
    if (e.start < i) continue
    if (e.start > i) parts.push({ t: text.slice(i, e.start) })
    parts.push({ t: text.slice(e.start, e.end), e })
    i = e.end
  }
  if (i < text.length) parts.push({ t: text.slice(i) })
  return (
    <p className="rounded-xl bg-fill px-3.5 py-2.5 leading-7" data-testid="highlighted-text">
      {parts.map((p, k) => {
        if (!p.e) return <span key={k}>{p.t}</span>
        const o = originOf(p.e, fallback)
        const border = o === 'refined' ? 'border-dashed' : o === 'rule' ? 'border-dotted' : ''
        return (
          <mark key={k} data-origin={o} title={`${p.e.type} [${p.e.start}, ${p.e.end}) · ${o}`} className={`rounded-sm border px-0.5 ${border} ${TYPE_STYLE[p.e.type]}`}>
            {p.t}<span className="sr-only"> ({p.e.type}, {o})</span>
            <sup aria-hidden className="ml-0.5 text-[10px] font-semibold">{p.e.type}{o === 'neural' || o === 'scripted' ? '' : ` · ${o}`}</sup>
          </mark>
        )
      })}
    </p>
  )
}

export function EntityTable({ entities, fallback }: { entities: Entity[]; fallback?: string }) {
  return (
    <table className="w-full text-left"><thead className="text-xs text-muted"><tr><th className="py-1 font-medium">Type</th><th className="font-medium">Span</th><th className="font-medium">Origin</th><th className="font-medium">Offsets</th><th className="font-medium">Confidence</th></tr></thead>
      <tbody>{entities.map((e) => {
        const notes = describeOp(e)
        return (
          <tr key={e.id} className="border-t border-line align-top" data-testid="entity-row" data-origin={originOf(e, fallback)}>
            <td className="py-1.5"><span className={`rounded-sm border px-1 text-xs ${TYPE_STYLE[e.type]}`}>{e.type}</span></td>
            <td>“{e.text}”{notes.map((n, k) => <div key={k} className="mt-0.5 text-xs text-muted">{n}</div>)}</td>
            <td><ProvenanceChip kind={originOf(e, fallback)} /></td>
            <td className="whitespace-nowrap pr-2 font-mono text-xs">[{e.start}, {e.end})</td>
            <td className="text-xs text-muted">{e.confidence == null ? '—' : e.confidence.toFixed(2)}<span className="sr-only"> uncalibrated</span></td>
          </tr>
        )
      })}</tbody></table>
  )
}

/** What the rules changed, step by step, plus a compact view of the raw neural output they started from. */
export function RefinementSummary({ a }: { a: Analysis }) {
  const ref = a.refinement
  if (!ref) return null
  const trace = ref.trace
  const changed = JSON.stringify(ref.raw_entities.map((e) => [e.type, e.start, e.end])) !== JSON.stringify(ref.entities.map((e) => [e.type, e.start, e.end]))
  return (
    <div className="space-y-3 border-t border-line pt-3" data-testid="refinement-summary">
      <p className="text-xs text-muted">Pipeline: <strong>{String(ref.config.preset).replace(/_/g, ' ')}</strong>. {changed ? 'Rules changed the neural output; the original is kept below.' : 'The rules left the neural output unchanged.'}</p>
      {trace.length > 0 && (
        <details open>
          <summary className="cursor-pointer text-xs font-semibold text-muted">What the rules did ({trace.length})</summary>
          <ul className="mt-1 space-y-0.5 text-xs" data-testid="refinement-trace">
            {trace.map((t, k) => (
              <li key={k}><span className="font-medium">{STAGE_LABEL[t.step] ?? t.step}</span> · {t.action}: {t.from ? `${fmt(t.from)} → ${fmt(t.to)}` : t.text ? fmt(t.text) : t.pattern ? `${t.pattern}: ${fmt(t.dependent)} depends on ${fmt(t.prerequisite)}` : ''}{t.reason ? ` — ${t.reason}` : ''}</li>
            ))}
          </ul>
        </details>
      )}
      <details>
        <summary className="cursor-pointer text-xs font-semibold text-muted">Raw neural output ({ref.raw_entities.length} spans)</summary>
        {ref.raw_entities.length === 0
          ? <p className="mt-1 text-xs text-muted">The model produced no spans.</p>
          : <ul className="mt-1 space-y-0.5 text-xs" data-testid="raw-entities">{ref.raw_entities.map((e) => <li key={e.id}><span className={`mr-1 rounded-sm border px-1 ${TYPE_STYLE[e.type]}`}>{e.type}</span>“{e.text}” <span className="font-mono text-muted">[{e.start}, {e.end})</span></li>)}</ul>}
      </details>
    </div>
  )
}

const rel = (r: Relation) => `“${r.source_text}” ${r.label} → “${r.target_text}”`

export function RawRelations({ a }: { a: Analysis }) {
  const ref = a.refinement
  if (!ref?.raw_relations) return null
  const by = new Map(ref.raw_entities.map((e) => [e.id, e.text]))
  return (
    <details className="text-xs">
      <summary className="cursor-pointer font-semibold text-muted">Relations the model gave on the raw spans ({ref.raw_relations.length})</summary>
      <ul className="mt-1 space-y-0.5">{ref.raw_relations.map((r, k) => <li key={k}>{rel({ ...r, source_text: by.get(r.source_id), target_text: by.get(r.target_id) })} <span className="text-muted">{r.score != null ? r.score.toFixed(2) : ''}</span></li>)}</ul>
    </details>
  )
}

export function RelationEdits({ a }: { a: Analysis }) {
  const edits = a.refinement?.relation_edits ?? []
  if (edits.length === 0) return null
  return (
    <div className="text-xs" data-testid="relation-edits">
      <div className="font-semibold text-muted">Owner links changed by rule</div>
      <ul className="mt-1 space-y-0.5">{edits.map((e, k) => (
        <li key={k}>{e.op === 'add_owner' ? 'Added' : 'Dropped'} <strong>{String(e.person)}</strong> as owner of “{String(e.task)}”
          {e.op === 'drop_cross_clause_owner' ? ` (the model gave ${e.model_score != null ? Number(e.model_score).toFixed(2) : 'a score'}, but another clause separates them)` : ` (${e.rule})`}</li>
      ))}</ul>
    </div>
  )
}

export function ConfigTable({ a }: { a: Analysis }) {
  const cfg = a.refinement?.config
  if (!cfg) return null
  return (
    <div>
      <div className="mb-1 text-xs font-semibold text-muted">Pipeline configuration · {String(cfg.preset).replace(/_/g, ' ')}</div>
      <table className="w-full text-left text-xs" data-testid="refine-config"><tbody>
        <tr className="border-b border-line"><td className="py-1 text-muted">Entity source</td><td>{String(cfg.entity_source)}</td></tr>
        {STAGE_FLAGS.map(([k, label]) => <tr key={k} className="border-b border-line"><td className="py-1 text-muted">{label}</td><td>{cfg[k] ? 'on' : 'off'}</td></tr>)}
      </tbody></table>
    </div>
  )
}
