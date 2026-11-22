import * as Dialog from '@radix-ui/react-dialog'
import * as Tabs from '@radix-ui/react-tabs'
import { useState } from 'react'
import { Sparkles, X } from 'lucide-react'
import type { Analysis, Participant, Relation, Suggestion } from '../../api/types'
import { ProvenanceChip } from '../../components/ProvenanceChip'
import { formatTemporal, nameOf } from '../../lib/format'
import { ConfigTable, EntityTable, RawRelations, RefinementSummary, RelationEdits, SpanView, TYPE_STYLE } from './RefinementPanels'

function summary(a: Analysis): string {
  const n = (t: string) => (a.entities ?? []).filter((e) => e.type === t).length
  const words: Array<[number, string, string]> = [[n('TASK'), 'task', 'tasks'], [n('PERSON'), 'person', 'people'], [n('TEMPORAL'), 'date', 'dates']]
  const parts = words.filter(([c]) => c > 0).map(([c, one, many]) => `${c} ${c === 1 ? one : many}`)
  return parts.length ? `Found ${parts.join(', ')}` : 'Nothing found'
}

type Props = { open: boolean; analysis: Analysis | undefined; loading: boolean; people: Participant[]; onClose: () => void }

export function InspectorDrawer({ open, analysis: a, loading, people, onClose }: Props) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/25" />
        <Dialog.Content aria-describedby={undefined} className="sheet fixed right-0 top-0 z-50 flex h-full w-[min(36rem,100vw)] flex-col bg-surface shadow-[var(--shadow-sheet)] focus:outline-none md:right-3 md:top-3 md:h-[calc(100%-1.5rem)] md:rounded-2xl" data-testid="inspector">
          <div className="flex items-center gap-3 px-5 pb-1 pt-4">
            <Sparkles size={18} className="text-accent" aria-hidden />
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-[17px] font-semibold leading-tight">How the AI read this</Dialog.Title>
              {a && <p className="text-xs text-faint">Message from {nameOf(people, a.message.sender_id)}</p>}
            </div>
            <Dialog.Close aria-label="Close inspector" className="rounded-full bg-fill p-1 text-muted hover:text-ink"><X size={16} /></Dialog.Close>
          </div>
          {loading && <p className="p-5 text-sm text-muted">Loading…</p>}
          {a && <InspectorBody a={a} people={people} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

const tab = 'whitespace-nowrap rounded-[7px] px-2.5 py-1 text-[13px] font-medium text-ink data-[state=active]:bg-surface data-[state=active]:shadow-[0_1px_3px_rgba(0,0,0,0.12)]'
const TABS: Array<[string, string]> = [['entities', 'Highlights'], ['relations', 'Links'], ['resolution', 'People & dates'], ['reconciliation', 'Decision'], ['provenance', 'Sources']]
const KEY: Array<[string, string]> = [['TASK', 'Task'], ['PERSON', 'Person'], ['TEMPORAL', 'Date']]

function InspectorBody({ a, people }: { a: Analysis; people: Participant[] }) {
  const [view, setView] = useState<'refined' | 'raw'>('refined')
  const canCompare = !!a.refinement && a.refinement.config.preset !== 'neural_only'
  return (
    <Tabs.Root defaultValue="entities" className="flex min-h-0 flex-1 flex-col">
      <div className="px-5 pt-3">
        {canCompare && (
          <div role="radiogroup" aria-label="Spans shown" className="mb-1 flex items-center gap-1 text-xs">
            <span className="mr-1 text-muted">Spans:</span>
            {(['refined', 'raw'] as const).map((v) => (
              <button key={v} role="radio" aria-checked={view === v} onClick={() => setView(v)}
                className={`rounded-full px-2.5 py-0.5 ${view === v ? 'bg-ink text-white' : 'bg-fill text-muted hover:text-ink'}`}>{v === 'raw' ? 'Raw neural' : 'Refined'}</button>
            ))}
          </div>
        )}
        <SpanView a={a} view={view} />
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted" aria-hidden>
          {KEY.map(([k, label]) => <span key={k} className="inline-flex items-center gap-1"><span className={`h-2.5 w-2.5 rounded-sm border ${TYPE_STYLE[k]}`} />{label}</span>)}
          {a.entities && <span className="ml-auto text-faint">{summary(a)}</span>}
        </div>
        {a.error && <p role="alert" className="mt-2 rounded-xl bg-danger-bg px-3 py-2 text-sm text-danger">{a.error}</p>}
      </div>
      <div className="mt-3 overflow-x-auto px-5">
        <Tabs.List aria-label="Inspector sections" className="segmented">
          {TABS.map(([t, label]) => <Tabs.Trigger key={t} value={t} className={tab}>{label}</Tabs.Trigger>)}
        </Tabs.List>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm">
        <Tabs.Content value="entities"><EntitiesTab a={a} /></Tabs.Content>
        <Tabs.Content value="relations"><RelationsTab a={a} /></Tabs.Content>
        <Tabs.Content value="resolution"><ResolutionTab a={a} people={people} /></Tabs.Content>
        <Tabs.Content value="reconciliation"><ReconciliationTab a={a} /></Tabs.Content>
        <Tabs.Content value="provenance"><ProvenanceTab a={a} /></Tabs.Content>
      </div>
    </Tabs.Root>
  )
}

function EntitiesTab({ a }: { a: Analysis }) {
  const ents = a.entities
  return (
    <div className="space-y-3">
      {ents === null && <p className="text-muted">No entities: this message was not analysed.</p>}
      {ents && ents.length === 0 && <p className="text-muted">{a.refinement ? 'No TASK, PERSON or TEMPORAL spans remain after refinement.' : 'The model found no TASK, PERSON or TEMPORAL spans in this message.'}</p>}
      {ents && ents.length > 0 && <EntityTable entities={ents} fallback={a.provenance.entities?.split(' ')[0]} />}
      <RefinementSummary a={a} />
      <p className="text-xs text-muted">Classes this model can produce: {a.classes_supported.join(', ')}. <strong>Not produced:</strong> {a.classes_not_produced.join(', ')}.</p>
    </div>
  )
}

function RelationCard({ r }: { r: Relation }) {
  return (
    <div className="rounded-xl border border-line p-3" data-testid="relation" data-provenance={r.provenance}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">“{r.source_text}”</span><span className="rounded-sm border border-line-strong bg-canvas px-1.5 text-xs font-medium">{r.label} →</span><span className="font-medium">“{r.target_text}”</span>
        <span className="ml-auto"><ProvenanceChip kind={r.provenance} /></span>
      </div>
      <p className="mt-1 text-xs text-muted">{r.score == null ? 'No model score (not produced by a trained model).' : `Score ${r.score.toFixed(3)} · uncalibrated softmax, not a probability.`}{r.model_version ? ` · ${r.model_version}` : ''}</p>
      {r.evidence_text && <p className="mt-1 border-l-2 border-line-strong pl-2 text-xs italic text-muted">“{r.evidence_text}”{r.rule ? ` — rule: ${r.rule}` : ''}{r.cue ? ` · cue “${r.cue}”` : ''}</p>}
    </div>
  )
}

function RelationsTab({ a }: { a: Analysis }) {
  const rels = a.relations
  const neural = rels.filter((r) => r.provenance === 'neural')
  const other = rels.filter((r) => r.provenance !== 'neural')
  return (
    <div className="space-y-3">
      {rels.length === 0 && <p className="text-muted">No typed relations were found between the spans.</p>}
      {neural.length > 0 && <div><div className="mb-1 text-xs font-semibold text-muted">Neural relation model{a.refinement ? ' (on the refined spans)' : ''}</div><div className="space-y-2">{neural.map((r, i) => <RelationCard key={i} r={r} />)}</div></div>}
      {other.length > 0 && <div><div className="mb-1 text-xs font-semibold text-muted">Generated by rules</div><div className="space-y-2">{other.map((r, i) => <RelationCard key={i} r={r} />)}</div></div>}
      <RelationEdits a={a} />
      <RawRelations a={a} />
      {a.no_link && a.no_link.length > 0 && <p className="text-xs text-muted">{a.no_link.length} other candidate pair{a.no_link.length > 1 ? 's were' : ' was'} judged unrelated or below the model's decision.</p>}
      <p className="text-xs text-muted">{a.score_note}</p>
    </div>
  )
}

function Temporal({ label, tv }: { label: string; tv: any }) {
  if (!tv) return null
  return (
    <div className="mt-1">
      <span className="text-muted">{label}:</span> “{tv.raw}” → <strong>{formatTemporal(tv, 'unresolved')}</strong>
      <span className="ml-2 text-xs text-muted">{tv.status}{tv.rule_id ? ` · rule ${tv.rule_id}` : ''}</span>
      {tv.assumptions?.length > 0 && <div className="text-xs text-muted">Assumptions applied: {tv.assumptions.join(', ')}</div>}
    </div>
  )
}

function ResolutionTab({ a, people }: { a: Analysis; people: Participant[] }) {
  const cands = a.candidates ?? []
  if (cands.length === 0) return <p className="text-muted">No task candidates were built for this message.</p>
  return (
    <div className="space-y-4">
      {cands.map((c: any) => (
        <div key={c.candidate_id} className="rounded-xl border border-line p-3">
          <p className="font-medium">{c.title}</p>
          <p className="mt-1">Owner: <strong>{c.assignee.participant_id ? nameOf(people, c.assignee.participant_id) : 'unresolved'}</strong> <span className="text-xs text-muted">({c.assignee.status.toLowerCase().replace(/_/g, ' ')}{c.assignee.basis ? ` · ${c.assignee.basis}` : ''})</span></p>
          <Temporal label="Due" tv={c.due} /><Temporal label="Scheduled" tv={c.scheduled} />
          {c.flags.length > 0 && <ul className="mt-2 space-y-0.5 text-xs">{c.flags.map((f: any) => <li key={f.code + f.field} className={f.severity === 'info' ? 'text-muted' : 'text-warn'}>{f.severity === 'info' ? '○' : '△'} {f.question ?? f.message}</li>)}</ul>}
        </div>
      ))}
      <p className="text-xs text-muted">Dates are resolved by rules against the message time and workspace timezone; unresolved values keep their raw text and are never guessed.</p>
    </div>
  )
}

function ReconciliationTab({ a }: { a: Analysis }) {
  const ps = a.proposals
  if (ps.length === 0) return <p className="text-muted">No operation was proposed for this message.</p>
  return (
    <div className="space-y-3">
      {ps.map((p: Suggestion) => (
        <div key={p.id} className="rounded-xl border border-line p-3">
          <div className="flex flex-wrap items-center gap-2"><span className="rounded-sm border border-line-strong bg-canvas px-1.5 text-xs font-medium">{p.operation}</span><span className="text-xs text-muted">{p.status}</span><span className="ml-auto"><ProvenanceChip kind="rule (cue-based)" /></span></div>
          <p className="mt-1 font-medium">{p.summary}</p>
          {p.note && <p className="text-xs text-muted">Trace: {p.note}</p>}
          {p.match?.ranked && p.match.ranked.length > 0 && (
            <div className="mt-2 text-xs"><div className="font-semibold text-muted">Referent candidates ({p.match.outcome?.toLowerCase().replace(/_/g, ' ')})</div>
              <ul className="mt-1 space-y-0.5">{p.match.ranked.map((r) => <li key={r.task_id}><span className="font-medium">{r.task_id}</span> · score {r.score} — {Object.entries(r.signals).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(', ')}</li>)}</ul>
            </div>
          )}
          {p.flags.length > 0 && <ul className="mt-2 space-y-0.5 text-xs">{p.flags.map((f) => <li key={f.code + f.field} className={f.severity === 'info' ? 'text-muted' : 'text-warn'}>{f.severity === 'info' ? '○' : '△'} {f.code.replace(/_/g, ' ').toLowerCase()}: {f.message}</li>)}</ul>}
        </div>
      ))}
      <p className="text-xs text-muted">Reconciliation is a conservative, cue-based state machine. It is not a trained matcher, and it shows explicit signals and scores, not model reasoning.</p>
    </div>
  )
}

function ProvenanceTab({ a }: { a: Analysis }) {
  const stages: Array<[string, string | undefined]> = [
    ['Entity extraction', a.provenance.entities], ['Span refinement', a.provenance.entity_refinement], ['Relation linking', a.provenance.relations], ['Owner links (rule edits)', a.provenance.relation_refinement], ['Dependency links', a.provenance.dependency_links],
    ['Dates (temporal)', a.provenance.temporal], ['Owner resolution', a.provenance.identity], ['Reconciliation', a.provenance.reconciliation],
  ]
  const exp = a.message.expected
  const actual = a.proposals.map((p) => p.operation)
  return (
    <div className="space-y-4">
      <table className="w-full text-left"><tbody>
        {stages.filter(([, v]) => v).map(([k, v]) => <tr key={k} className="border-b border-line"><td className="py-1.5 text-muted">{k}</td><td><ProvenanceChip kind={v!} /></td></tr>)}
      </tbody></table>
      <ConfigTable a={a} />
      <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-xs">
        <dt className="text-muted">Mode</dt><dd>{a.message.mode}</dd>
        <dt className="text-muted">Run</dt><dd className="font-mono">{a.run_id ?? '—'}{a.duration_ms != null ? ` · ${a.duration_ms} ms` : ''}</dd>
        {Object.entries(a.model_versions).map(([k, v]) => [<dt key={`k${k}`} className="text-muted">Model: {k}</dt>, <dd key={`v${k}`}>{v}</dd>])}
        <dt className="text-muted">Training data</dt><dd>MailEx-derived SILVER labels, provisional, not human-verified</dd>
      </dl>
      {exp && (
        <div className="rounded-xl bg-warn-bg p-3 text-xs text-warn">
          <div className="font-semibold">Scripted expectation (not a model prediction)</div>
          <p className="mt-1">Expected: {exp.operations.join(', ')} — {exp.note}</p>
          <p>Actual: {actual.join(', ') || 'none'} {a.message.matches_expectation ? '✓ matches' : '✕ differs'}</p>
        </div>
      )}
      <p className="text-xs text-muted">Attention weights and logits are not shown: they are not a faithful explanation. Evidence spans and rule traces are.</p>
    </div>
  )
}
