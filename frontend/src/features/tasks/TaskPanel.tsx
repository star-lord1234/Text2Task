import * as ToggleGroup from '@radix-ui/react-toggle-group'
import { ChevronRight, Inbox } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import type { Participant, Suggestion, TaskView } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { nameOf } from '../../lib/format'
import { canDecide, canDismiss, reviewerNames } from '../../lib/suggest'
import { SuggestionItem } from './SuggestionItem'
import { TaskRow } from './TaskRow'

type Props = {
  tasks: TaskView[]
  suggestions: Suggestion[]
  people: Participant[]
  active: Participant | null
  busy: boolean
  onOpenTask: (id: string) => void
  onSource: (messageId: string) => void
  onAccept: (s: Suggestion, edits?: Record<string, unknown>) => void
  onEdit: (s: Suggestion) => void
  onDismiss: (s: Suggestion) => void
  onComplete?: (t: TaskView) => void
  onSwitchUser?: (id: string) => void
}

const CLOSED = new Set(['done', 'canceled'])

function Disclosure({ label, count, children, testId, defaultOpen }: { label: string; count: number; children: ReactNode; testId?: string; defaultOpen?: boolean }) {
  return (
    <details className="group" data-testid={testId} open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-1 py-1.5 text-[13px] font-semibold text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight size={14} className="transition-transform group-open:rotate-90" aria-hidden />{label}<span className="font-normal text-faint">{count}</span>
      </summary>
      <div className="mt-1.5">{children}</div>
    </details>
  )
}

export function TaskPanel({ tasks, suggestions, people, active, busy, onOpenTask, onSource, onAccept, onEdit, onDismiss, onComplete, onSwitchUser }: Props) {
  const [view, setView] = useState<'mine' | 'all'>('mine')
  const mine = view === 'mine'
  const me = active?.id ?? null
  const visible = useMemo(() => tasks.filter((t) => (mine ? t.owner_id === me : true)), [tasks, mine, me])
  const open = visible.filter((t) => !CLOSED.has(t.ui_status))
  const closed = visible.filter((t) => CLOSED.has(t.ui_status))
  const pending = suggestions.filter((s) => s.status === 'pending')
  const forMe = pending.filter((s) => canDecide(s, me))
  const forOthers = pending.filter((s) => !canDecide(s, me))

  const groups: Array<{ owner: string | null; items: TaskView[] }> = useMemo(() => {
    if (mine) return [{ owner: me, items: open }]
    const ids = [...people.map((p) => p.id), null]
    return ids.map((id) => ({ owner: id, items: open.filter((t) => t.owner_id === id) })).filter((g) => g.items.length > 0)
  }, [mine, open, people, me])

  const card = (s: Suggestion) => (
    <SuggestionItem key={s.id} s={s} busy={busy} tasks={tasks} people={people} me={me} onAccept={onAccept} onEdit={onEdit} onDismiss={onDismiss} onSource={onSource}
      canDecide={canDecide(s, me)} canDismiss={canDismiss(s, me)} waitingFor={reviewerNames(s, people)}
      onSwitchTo={onSwitchUser && s.reviewer_ids.length === 1 && !canDecide(s, me) ? () => onSwitchUser(s.reviewer_ids[0]) : undefined} />
  )
  const complete = (t: TaskView) => (onComplete && t.owner_id === me ? onComplete : undefined)

  return (
    <section aria-label="Tasks" className="flex min-h-0 flex-1 flex-col bg-canvas">
      <div className="flex items-center gap-3 border-b border-line bg-surface px-4 py-2.5">
        <h2 className="text-[17px] font-bold">Tasks</h2>
        <ToggleGroup.Root type="single" value={view} onValueChange={(v) => v && setView(v as 'mine' | 'all')} aria-label="Task view" className="segmented ml-auto">
          <ToggleGroup.Item value="mine">Mine</ToggleGroup.Item>
          <ToggleGroup.Item value="all">Team</ToggleGroup.Item>
        </ToggleGroup.Root>
      </div>

      <div className="scroll-thin min-h-0 flex-1 space-y-5 overflow-y-auto p-3">
        {forMe.length > 0 && (
          <div>
            <h3 className="mb-2 flex items-center gap-2 px-1 text-[15px] font-bold">
              Needs you <span className="rounded-full bg-[#e01e5a] px-1.5 text-xs font-bold text-white" data-testid="queue-count">{forMe.length}</span>
            </h3>
            <ul className="space-y-2.5">{forMe.map(card)}</ul>
          </div>
        )}

        <div>
          <h3 className="mb-2 px-1 text-[15px] font-bold">{mine ? 'My tasks' : 'Team tasks'}</h3>
          {open.length === 0 ? (
            <div className="group-list flex flex-col items-center gap-1 px-6 py-8 text-center">
              <Inbox size={28} className="text-line-strong" aria-hidden />
              <p className="text-sm font-medium">{mine ? `Nothing on ${active?.name ? `${active.name}'s` : 'your'} plate` : 'No open tasks'}</p>
              <p className="text-[13px] text-muted">{forMe.length > 0 ? 'Accept a suggestion above to add it here.' : 'Tasks appear once someone accepts them.'}</p>
            </div>
          ) : groups.map((g) => (
            <div key={g.owner ?? 'none'} className="mb-3 last:mb-0">
              {!mine && <h4 className="mb-1 flex items-center gap-2 px-1 text-[13px] font-semibold text-muted"><Avatar person={people.find((p) => p.id === g.owner) ?? null} size={16} />{nameOf(people, g.owner)}</h4>}
              <ul className="group-list">{g.items.map((t) => <TaskRow key={t.id} task={t} people={people} showOwner={false} onOpen={onOpenTask} onSource={onSource} onComplete={complete(t)} />)}</ul>
            </div>
          ))}
        </div>

        {forOthers.length > 0 && (
          <Disclosure label="Waiting on teammates" count={forOthers.length} testId="waiting-on-others" defaultOpen={forMe.length === 0}>
            <ul className="space-y-2">{forOthers.map(card)}</ul>
          </Disclosure>
        )}

        {closed.length > 0 && (
          <Disclosure label="Done or canceled" count={closed.length}>
            <ul className="group-list">{closed.map((t) => <TaskRow key={t.id} task={t} people={people} showOwner={!mine} onOpen={onOpenTask} />)}</ul>
          </Disclosure>
        )}
      </div>
    </section>
  )
}
