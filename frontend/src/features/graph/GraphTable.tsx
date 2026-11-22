import type { GraphData, Participant } from '../../api/types'
import { nameOf } from '../../lib/format'

/** Keyboard- and screen-reader-friendly alternative to the canvas: the same graph as two plain tables. */
export function GraphTable({ graph, people, onSelectEdge, onSelectNode }: { graph: GraphData; people: Participant[]; onSelectEdge: (id: string) => void; onSelectNode: (id: string) => void }) {
  const title = (id: string) => graph.nodes.find((n) => n.id === id)?.title ?? id
  return (
    <div className="space-y-6 p-4 text-sm">
      <table className="w-full border-collapse"><caption className="mb-1 text-left font-semibold">Tasks</caption>
        <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-1 pr-3 font-medium">Task</th><th className="pr-3 font-medium">Owner</th><th className="pr-3 font-medium">State</th><th className="font-medium">Waiting on</th></tr></thead>
        <tbody>{graph.nodes.map((n) => (
          <tr key={n.id} className="border-b border-line">
            <td className="py-1.5 pr-3"><button className="text-left font-medium hover:underline" onClick={() => onSelectNode(n.id)}>{n.title}</button></td>
            <td className="pr-3">{nameOf(people, n.owner_id)}</td><td className="pr-3">{n.derived_state.replace(/_/g, ' ')}</td><td>{n.blocked_by.map(title).join(', ') || '—'}</td>
          </tr>))}
        </tbody>
      </table>
      <table className="w-full border-collapse"><caption className="mb-1 text-left font-semibold">Dependencies (prerequisite → dependent)</caption>
        <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-1 pr-3 font-medium">Prerequisite</th><th className="pr-3 font-medium">Dependent</th><th className="pr-3 font-medium">State</th><th className="font-medium">Source</th></tr></thead>
        <tbody>
          {graph.edges.length === 0 && <tr><td colSpan={4} className="py-3 text-muted">No confirmed dependencies yet.</td></tr>}
          {graph.edges.map((e) => (
            <tr key={e.id} className="border-b border-line">
              <td className="py-1.5 pr-3"><button className="text-left hover:underline" onClick={() => onSelectEdge(e.id)}>{title(e.source)}</button></td>
              <td className="pr-3">{title(e.target)}</td><td className="pr-3">{e.kind === 'held' ? `held (${e.reason.split(':')[0].toLowerCase()})` : e.kind}</td><td>{e.source_message_id ?? '—'}</td>
            </tr>))}
        </tbody>
      </table>
    </div>
  )
}
