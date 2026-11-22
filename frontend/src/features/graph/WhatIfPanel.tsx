import type { GraphData, GraphNode } from '../../api/types'
import { useImpact } from '../../api/hooks'
import { LIFECYCLE_LABEL } from '../../lib/transitions'

const OPTIONS: Array<[string, string]> = [['completed', 'completed'], ['cancelled', 'canceled'], ['open', 'reopened (back to to-do)']]

/** What-if analysis: calls the existing Phase 6 impact function. Nothing is changed. */
export function WhatIfPanel({ graph, task, selected, onSelect }: { graph: GraphData; task: GraphNode; selected: string | null; onSelect: (status: string | null) => void }) {
  const impact = useImpact(selected ? task.id : null, selected)
  const title = (id: string) => graph.nodes.find((n) => n.id === id)?.title ?? id
  const current = LIFECYCLE_LABEL[task.status] ?? task.status
  const other = OPTIONS.filter(([v]) => v !== task.status)
  const d = impact.data
  const nothing = d && !d.became_ready.length && !d.became_blocked.length && !d.became_review.length
  return (
    <section aria-label="What if" className="border-t border-line p-4 text-sm" data-testid="what-if">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">What if…</h3>
      <p className="mt-1 text-xs text-muted">“{task.title}” is {current.toLowerCase()}. Preview the knock-on effect. Nothing is changed.</p>
      <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="Scenario to preview">
        {other.map(([v, label]) => (
          <button key={v} aria-pressed={selected === v} onClick={() => onSelect(selected === v ? null : v)}
            className={`rounded-full px-2.5 py-1 text-xs font-medium ${selected === v ? 'bg-ink text-white' : 'bg-surface text-ink hover:bg-line'}`}>…it were {label}</button>
        ))}
      </div>
      {selected && impact.isLoading && <p className="mt-2 text-xs text-muted">Calculating…</p>}
      {d && (
        <div className="mt-3 space-y-1 text-xs" aria-live="polite" data-testid="what-if-result">
          {d.became_ready.length > 0 && <p className="text-ok">Becomes ready: <strong>{d.became_ready.map(title).join(', ')}</strong></p>}
          {d.became_blocked.length > 0 && <p className="text-warn">Becomes blocked: <strong>{d.became_blocked.map(title).join(', ')}</strong></p>}
          {d.became_review.length > 0 && <p className="text-warn">Needs review (a prerequisite was canceled): <strong>{d.became_review.map(title).join(', ')}</strong></p>}
          {nothing && <p className="text-muted">No other task changes state.</p>}
        </div>
      )}
    </section>
  )
}
