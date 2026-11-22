import { Check, ChevronRight, Lock } from 'lucide-react'
import type { Participant, TaskView } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { StatusBadge } from '../../components/StatusBadge'
import { formatTemporal } from '../../lib/format'

type Props = {
  task: TaskView
  people: Participant[]
  showOwner: boolean
  onOpen: (id: string) => void
  onSource?: (messageId: string) => void
  /** Set when the viewer owns the task and may tick it off. */
  onComplete?: (t: TaskView) => void
}

/** iOS-style list row: a tick circle (owner only), title, one quiet line of facts, chevron. */
export function TaskRow({ task: t, people, showOwner, onOpen, onComplete }: Props) {
  const owner = people.find((p) => p.id === t.owner_id) ?? null
  const pending = t.pending_changes.due
  const closed = t.ui_status === 'done' || t.ui_status === 'canceled'
  const blocked = t.ui_status === 'blocked'
  const facts = [
    t.due ? `Due ${formatTemporal(t.due)}` : t.scheduled ? `Planned ${formatTemporal(t.scheduled)}` : null,
    t.blocked_by_count > 0 && !closed ? `Waiting on ${t.blocked_by_count}` : null,
    t.blocks_count > 0 && !closed ? `Blocks ${t.blocks_count}` : null,
  ].filter(Boolean)
  const tickable = !!onComplete && !closed && !blocked
  return (
    <li className="enter flex items-center gap-3 px-4 py-2.5">
      {tickable ? (
        <button onClick={() => onComplete!(t)} aria-label={`Mark done: ${t.title}`} title="Mark done"
          className="group flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border-2 border-line-strong hover:border-ok">
          <Check size={13} strokeWidth={3} className="text-ok opacity-0 group-hover:opacity-100" aria-hidden />
        </button>
      ) : closed ? (
        <span aria-hidden className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-ok text-white"><Check size={13} strokeWidth={3} /></span>
      ) : blocked ? (
        <span aria-hidden className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-warn-bg text-warn"><Lock size={12} /></span>
      ) : <span aria-hidden className="h-[22px] w-[22px] shrink-0 rounded-full border-2 border-dashed border-line-strong" />}

      <button onClick={() => onOpen(t.id)} className="flex min-w-0 flex-1 items-center gap-2 text-left" aria-label={`Open task: ${t.title}`}>
        <span className="min-w-0 flex-1">
          <span className={`block truncate font-medium first-letter:uppercase ${closed ? 'text-faint line-through' : ''}`}>{t.title}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[13px] text-muted">
            {t.ui_status !== 'todo' && !closed && <StatusBadge status={t.ui_status} />}
            {facts.length > 0 && <span>{facts.join(' · ')}</span>}
          </span>
          {pending && <span className="mt-0.5 block text-xs text-warn">New date {formatTemporal(pending.value)} awaiting OK</span>}
        </span>
        {showOwner && <span title={owner?.name ?? 'Unassigned'}><Avatar person={owner} size={22} /></span>}
        <ChevronRight size={16} className="shrink-0 text-line-strong" aria-hidden />
      </button>
    </li>
  )
}
