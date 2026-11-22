import type { ReactNode } from 'react'
import { useEvaluation } from '../api/hooks'
import type { PhaseReport, Prf } from '../api/types'

const f = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(3))

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <table className="w-full text-left text-sm">
      <thead><tr className="border-b border-line text-xs text-muted">{head.map((h, i) => <th key={h} className={`py-1.5 pr-3 font-medium ${i ? 'text-right' : ''}`}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i} className="border-b border-line last:border-0">{r.map((c, j) => <td key={j} className={`py-1.5 pr-3 ${j ? 'text-right tabular-nums' : ''}`}>{c}</td>)}</tr>)}</tbody>
    </table>
  )
}
const prfRow = (name: string, p?: Prf) => [name, f(p?.precision), f(p?.recall), f(p?.f1), p?.support ?? '—']

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="mb-6"><h2 className="section-label mb-1.5 px-1">{title}</h2><div className="group-list p-4">{children}</div></section>
}
function Limits({ items }: { items?: string[] }) {
  if (!items?.length) return null
  return <div className="mt-3"><h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Limitations</h3><ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muted">{items.map((l) => <li key={l}>{l}</li>)}</ul></div>
}
const scalars = (o: Record<string, unknown>) => Object.entries(o).filter(([, v]) => ['number', 'string', 'boolean'].includes(typeof v))

function Phase({ p }: { p: PhaseReport }) {
  return (
    <details className="mb-2 rounded-xl bg-fill p-3">
      <summary className="cursor-pointer text-sm font-medium">{p.title}</summary>
      {!p.available ? <p className="mt-2 text-sm text-muted">The saved report is missing.</p> : (
        <div className="mt-2">
          <p className="text-xs text-muted">{p.provenance}</p>
          {Object.entries(p.sections ?? {}).map(([name, o]) => (
            <div key={name} className="mt-3"><h4 className="text-xs font-medium">{name.replace(/_/g, ' ')}</h4>
              <dl className="mt-1 grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 text-sm">{scalars(o).map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k.replace(/_/g, ' ')}</dt><dd className="text-right tabular-nums">{typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(3) : String(v)}</dd></div>)}</dl>
            </div>
          ))}
          <Limits items={p.limitations} />
        </div>
      )}
    </details>
  )
}

export function EvaluationPage() {
  const q = useEvaluation()
  const d = q.data
  if (q.isLoading) return <p className="p-6 text-sm text-muted">Loading…</p>
  if (!d) return <p className="p-6 text-sm text-danger">Saved results could not be loaded.</p>
  const e = d.entities, r = d.relations
  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto bg-canvas">
      <div className="flex items-center gap-3 border-b border-line bg-surface px-4 py-2.5">
        <h1 className="text-[17px] font-bold">Model results</h1>
        <span className="hidden text-[13px] text-muted sm:inline">How well the AI models score</span>
      </div>
    <div className="mx-auto max-w-4xl p-4">
      <p className="rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn">{d.statement}</p>
      <details className="mb-5 mt-2 px-1 text-xs text-muted">
        <summary className="cursor-pointer">Where these numbers come from{d.missing.length > 0 ? ` · ${d.missing.length} missing` : ''}</summary>
        <p className="mt-1">Read from saved files: {d.sources.join(' · ')}. Nothing here is recomputed. {d.missing.length > 0 && `Missing: ${d.missing.join(', ')}.`}</p>
      </details>

      <Section title="Entity extraction">
        {!e.available ? <p className="text-sm text-muted">No saved entity metrics found.</p> : <>
          <p className="mb-2 text-sm text-muted">{e.model}. {e.metric}.</p>
          <Table head={['Type', 'Precision', 'Recall', 'F1', 'Support']} rows={[prfRow('All (micro)', e.overall), ...Object.entries(e.per_type ?? {}).map(([k, v]) => prfRow(k, v))]} />
          <p className="mt-2 text-sm text-muted">TASK spans are the weak point of the model currently used by the app: it finds people and dates far better than task phrases.</p>
          {e.rule_baseline && <p className="mt-2 text-sm text-muted">Rule baseline ({e.rule_baseline.name}, {e.rule_baseline.rows} validation rows): lenient F1 {f(e.rule_baseline.lenient_f1)}, strict F1 {f(e.rule_baseline.strict_f1)}.</p>}
          {e.mailex_runs && <div className="mt-3"><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Earlier span-matching runs</h3>
            <Table head={['Run', 'Strict F1', 'Lenient F1', 'Overlap F1']} rows={e.mailex_runs.map((x) => [x.run, f(x.strict_f1), f(x.lenient_f1), f(x.overlap_f1)])} /></div>}
          <p className="mt-2 text-xs text-muted">{e.note}</p>
        </>}
      </Section>

      <Section title="Relation extraction">
        {!r.available || !r.mode_a ? <p className="text-sm text-muted">No saved relation metrics found.</p> : <>
          <p className="mb-2 text-sm text-muted">{r.model}, {r.split} split, {r.pairs} candidate pairs, using the reference entity spans (“Mode A”).</p>
          <Table head={['Label (neural)', 'Precision', 'Recall', 'F1', 'Support']} rows={Object.entries(r.mode_a.neural.per_label).map(([k, v]) => prfRow(k, v))} />
          <p className="mt-2 text-sm">Neural micro F1 <b>{f(r.mode_a.neural.micro_f1)}</b>, macro F1 {f(r.mode_a.neural.macro_f1)}; rule baseline micro {f(r.mode_a.rule.micro_f1)}, macro {f(r.mode_a.rule.macro_f1)}. False-link rate on unlinked pairs {(r.mode_a.neural.none_false_positive_rate * 100).toFixed(1)}%.</p>
          {r.mode_b && <div className="mt-3"><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">End to end with predicted entities (“Mode B”)</h3>
            <Table head={['Matching', 'Micro F1', 'Candidate recall']} rows={Object.entries(r.mode_b).map(([k, v]) => [k.replace('_', ' '), f(v.micro_f1), f(v.candidate_recall)])} />
            <p className="mt-1 text-xs text-muted">These low numbers mostly reflect mismatched span definitions between references and the entity model, not relation quality.</p></div>}
          <Limits items={r.limitations} />
        </>}
      </Section>

      <Section title="Rule-based stages and functional checks">
        <p className="mb-2 text-sm text-muted">These have no labelled data. The reports describe developer-authored scenarios, fuzz tests and corpus replays, which test behaviour rather than accuracy.</p>
        {d.phases.map((p) => <Phase key={p.id} p={p} />)}
      </Section>
    </div>
    </div>
  )
}
