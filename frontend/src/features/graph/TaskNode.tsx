import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { GraphNode, Participant } from '../../api/types'
import { StatusBadge } from '../../components/StatusBadge'
import { Avatar } from '../../components/Avatar'
import { fmtDay } from '../../lib/format'
import { NODE_H, NODE_W } from './layout'

export type TaskNodeData = { node: GraphNode; owner: Participant | null; dimmed: boolean; highlight: 'none' | 'selected' | 'ready' | 'blocked' | 'done' | 'review'; compact: boolean; [k: string]: unknown }
export type TaskFlowNode = Node<TaskNodeData, 'task'>

export const uiStatusOf = (n: GraphNode): string =>
  ({ blocked: 'blocked', blocked_cancelled_prereq: 'needs_review', done: 'done', cancelled: 'canceled' } as Record<string, string>)[n.derived_state] ?? (n.status === 'in_progress' ? 'in_progress' : 'todo')

const RING: Record<string, string> = { selected: 'ring-2 ring-accent', ready: 'ring-2 ring-ok', blocked: 'ring-2 ring-warn', done: 'ring-2 ring-ok', review: 'ring-2 ring-warn', none: '' }

/** One task: border colour = owner; status is an icon plus a label. Only the essentials, technical detail lives in the Inspector. */
export function TaskNode({ data }: NodeProps<TaskFlowNode>) {
  const { node: n, owner, dimmed, highlight, compact } = data
  const status = uiStatusOf(n)
  const extra = n.derived_state === 'blocked' && n.blocked_by.length ? `by ${n.blocked_by.length}` : undefined
  return (
    <div role="group" aria-label={`${n.title}, ${owner?.name ?? 'unassigned'}`} data-testid={`node-${n.id}`} data-state={n.derived_state}
      className={`rounded-xl border border-line bg-surface px-3 py-2 shadow-[0_1px_3px_rgba(0,0,0,0.08)] ${RING[highlight]} ${dimmed ? 'opacity-35' : ''}`}
      style={{ width: NODE_W, height: NODE_H, borderLeft: `4px solid ${owner?.color ?? '#c7c7cc'}` }}>
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-faint" />
      <div className="truncate text-[14px] font-semibold first-letter:uppercase" title={n.title}>{n.title}</div>
      <div className="mt-1 flex items-center gap-1.5 text-xs text-muted">
        <Avatar person={owner} size={16} /><span className="truncate">{owner?.name ?? 'Unassigned'}</span>
        {!compact && n.due && n.due_status === 'RESOLVED' && <span className="ml-auto whitespace-nowrap">{fmtDay(n.due).replace(/^\w+ /, '')}</span>}
      </div>
      <div className="mt-1"><StatusBadge status={status} extra={extra} /></div>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-faint" />
    </div>
  )
}
export { NODE_H, NODE_W }
