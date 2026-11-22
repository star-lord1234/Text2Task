import { ArrowUpRight } from 'lucide-react'
import type { GraphData, GraphEdge, GraphNode, Participant } from '../../api/types'
import { ProvenanceChip } from '../../components/ProvenanceChip'
import { StatusBadge } from '../../components/StatusBadge'
import { formatTemporal, nameOf } from '../../lib/format'
import { uiStatusOf } from './TaskNode'

type Props = {
  graph: GraphData
  edge: GraphEdge | null
  node: GraphNode | null
  people: Participant[]
  busy: boolean
  onInspect: (messageId: string) => void
  onOpenTask: (id: string) => void
  onRemove: (id: string) => void
  onReconsider: (id: string) => void
}

const btn = 'btn btn-gray btn-sm'

export function EdgeDetails({ graph, edge, node, people, busy, onInspect, onOpenTask, onRemove, onReconsider }: Props) {
  const by = (id: string) => graph.nodes.find((n) => n.id === id)
  if (edge) {
    const pre = by(edge.source), dep = by(edge.target)
    return (
      <div className="space-y-4 p-4 text-sm" data-testid="edge-details">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Dependency</h3>
          <p className="mt-1 font-medium">{pre?.title ?? edge.source}</p>
          <p className="text-muted">is a prerequisite of</p>
          <p className="font-medium">{dep?.title ?? edge.target}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-2 py-px text-xs font-medium ${edge.kind === 'held' ? 'bg-danger-bg text-danger' : edge.kind === 'proposed' ? 'bg-fill text-muted' : 'bg-ok-bg text-ok'}`}>
            {edge.kind === 'held' ? 'held for review' : edge.kind}
          </span>
          <ProvenanceChip kind={edge.source_kind} />
        </div>
        {edge.kind === 'held' && <p className="rounded-xl bg-danger-bg px-3 py-2 text-xs text-danger" role="note">{edge.reason}</p>}
        {edge.evidence && (
          <div>
            <h4 className="text-xs font-semibold text-muted">Evidence</h4>
            <blockquote className="mt-1 border-l-2 border-line-strong pl-2 text-sm italic text-muted">“{edge.evidence}”</blockquote>
          </div>
        )}
        {edge.source_message_id && <button className="inline-flex items-center gap-1 text-left text-xs text-accent hover:underline" onClick={() => onInspect(edge.source_message_id!)}>Open the source message in the Inspector <ArrowUpRight size={12} aria-hidden /></button>}
        <div>
          <h4 className="text-xs font-semibold text-muted">Checks</h4>
          <ul className="mt-1 space-y-0.5 text-xs">
            {edge.kind === 'accepted' && <li className="text-ok">✓ The accepted graph is acyclic</li>}
            {edge.kind === 'held' && <li className="text-danger">✕ {edge.reason.split(':')[0]}</li>}
            <li className="text-ok">✓ Not inferred from message or date order</li>
            {edge.warnings.length === 0 ? <li className="text-muted">○ No warnings</li> : edge.warnings.map((w) => <li key={w.code} className="text-warn">△ {w.message}</li>)}
          </ul>
        </div>
        {dep && edge.kind === 'accepted' && (
          <p className="text-xs text-muted">Effect: “{dep.title}” is currently <strong className="text-ink">{dep.derived_state.replace(/_/g, ' ')}</strong>.</p>
        )}
        <div className="flex flex-wrap gap-2">
          {edge.kind !== 'held' && <button className={btn} disabled={busy} onClick={() => onRemove(edge.id)}>Remove edge</button>}
          {edge.kind === 'held' && <button className={btn} disabled={busy} onClick={() => onReconsider(edge.id)}>Reconsider</button>}
        </div>
        <p className="text-xs text-faint">Removing keeps a record of who removed it and why.</p>
      </div>
    )
  }
  if (node) {
    const owner = nameOf(people, node.owner_id)
    return (
      <div className="space-y-3 p-4 text-sm" data-testid="node-details">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Task</h3>
        <p className="font-medium">{node.title}</p>
        <div className="flex items-center gap-2 text-xs text-muted"><StatusBadge status={uiStatusOf(node)} /><span>{owner}</span></div>
        <p className="text-xs text-muted">Due: {node.due ? formatTemporal({ raw: node.due, status: node.due_status ?? 'RESOLVED', value: node.due, start: node.due, end: node.due, granularity: 'DATE', assumptions: [] }) : 'No confirmed due date'}</p>
        {node.blocked_by.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-muted">Waiting on</h4>
            <ul className="mt-1 list-inside list-disc text-sm">{node.blocked_by.map((id) => <li key={id}>{by(id)?.title ?? id}</li>)}</ul>
          </div>
        )}
        {node.root_blockers.length > 0 && <p className="text-xs text-muted">Start with: {node.root_blockers.map((id) => by(id)?.title ?? id).join(', ')}</p>}
        {node.cancelled_prereqs.length > 0 && <p className="rounded-xl bg-warn-bg px-3 py-2 text-xs text-warn">A prerequisite was canceled. Cancellation does not satisfy a dependency; this needs review.</p>}
        <button className={btn} onClick={() => onOpenTask(node.id)}>Open task details</button>
      </div>
    )
  }
  return <p className="p-4 text-sm text-muted">Tap a task or an arrow to see the details.</p>
}
