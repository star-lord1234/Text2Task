import * as Dialog from '@radix-ui/react-dialog'
import { ChevronRight, Sparkles, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { HistoryEvent, Participant, TaskDetail, TaskView } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { ProvenanceChip } from '../../components/ProvenanceChip'
import { StatusBadge } from '../../components/StatusBadge'
import { formatTemporal, formatTime, nameOf } from '../../lib/format'
import { LIFECYCLE_LABEL, NEXT_STATUS } from '../../lib/transitions'

type Props = {
  task: TaskDetail | undefined
  loading: boolean
  people: Participant[]
  /** Other tasks, so dependencies show titles rather than ids. */
  tasks?: TaskView[]
  activeId: string | null
  saving: boolean
  onClose: () => void
  onSave: (changes: Record<string, unknown>, expectedVersion: number) => void
  onInspect: (messageId: string) => void
  onOpenTask: (id: string) => void
}

const OP_TEXT: Record<string, string> = {
  CREATE_TASK: 'created the task', MANUAL_EDIT: 'edited', UPDATE_ASSIGNEE: 'changed the owner', PROPOSE_DUE_DATE_CHANGE: 'proposed a new date',
  CONFIRM_DUE_DATE_CHANGE: 'confirmed the new date', COMPLETE_TASK: 'marked it done', CANCEL_TASK: 'canceled it', UPDATE_STATUS: 'changed the status',
  ADD_DEPENDENCY: 'added a dependency', REJECT_PENDING_CHANGE: 'declined a date change',
}

function brief(v: unknown, people: Participant[]): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return people.find((p) => p.id === v)?.name ?? LIFECYCLE_LABEL[v] ?? v
  if (typeof v === 'object' && 'raw' in (v as any)) return formatTemporal(v as any)
  if (typeof v === 'object' && 'value' in (v as any)) return brief((v as any).value, people)
  const s = JSON.stringify(v)
  return s.length > 60 ? `${s.slice(0, 60)}…` : s
}

function HistoryItem({ h, people }: { h: HistoryEvent; people: Participant[] }) {
  const create = h.field === '__create__'
  const actor = people.find((p) => p.id === h.actor) ?? null
  return (
    <li className="flex gap-2.5 px-3 py-2.5">
      <Avatar person={actor} size={22} />
      <div className="min-w-0 flex-1 text-sm">
        <p><span className="font-semibold">{h.actor ? nameOf(people, h.actor) : 'Someone'}</span> {OP_TEXT[h.operation] ?? h.operation.replace(/_/g, ' ').toLowerCase()}
          <span className="ml-1.5 text-xs text-faint">{formatTime(h.timestamp)}</span></p>
        {!create && <p className="text-[13px] text-muted">{h.field.replace(/_/g, ' ')}: {brief(h.before, people)} → {brief(h.after, people)}</p>}
      </div>
      <ProvenanceChip kind={h.source_kind} />
    </li>
  )
}

export function TaskDetails({ task: t, loading, onClose, ...rest }: Props) {
  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/25" />
        <Dialog.Content aria-describedby={undefined} className="sheet fixed right-0 top-0 z-50 flex h-full w-[min(28rem,100vw)] flex-col bg-canvas shadow-[var(--shadow-sheet)] focus:outline-none md:right-3 md:top-3 md:h-[calc(100%-1.5rem)] md:rounded-2xl">
          <div className="flex items-center px-4 pb-1 pt-3">
            <Dialog.Title className="flex-1 text-[13px] font-semibold uppercase tracking-wide text-faint">Task</Dialog.Title>
            <Dialog.Close aria-label="Close task details" className="rounded-full bg-line p-1 text-muted hover:text-ink"><X size={16} /></Dialog.Close>
          </div>
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 pb-6">
            {loading && <p className="py-4 text-sm text-muted">Loading…</p>}
            {t && <Body key={`${t.id}-${t.version}`} t={t} {...rest} />}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

const Row = ({ label, children }: { label: string; children: ReactNode }) => (
  <div className="row flex min-h-11 items-center gap-3 px-3 py-1.5"><span className="w-20 shrink-0 text-sm text-muted">{label}</span><div className="min-w-0 flex-1 text-right">{children}</div></div>
)
const bare = 'w-full bg-transparent py-1 text-right outline-none placeholder:text-faint disabled:text-faint'

function Body({ t, people, tasks = [], activeId, saving, onSave, onInspect, onOpenTask }: Omit<Props, 'task' | 'loading' | 'onClose'> & { t: TaskDetail }) {
  const [title, setTitle] = useState(t.title)
  const [owner, setOwner] = useState(t.owner_id ?? '')
  const [status, setStatus] = useState(t.lifecycle)
  const [due, setDue] = useState('')
  const next = NEXT_STATUS[t.lifecycle] ?? []
  const dirty = title !== t.title || owner !== (t.owner_id ?? '') || status !== t.lifecycle || due.trim() !== ''
  const titleOf = (id: string) => tasks.find((x) => x.id === id)?.title ?? id
  const save = () => {
    const changes: Record<string, unknown> = {}
    if (title !== t.title && title.trim()) changes.title = title.trim()
    if (owner !== (t.owner_id ?? '')) changes.owner_id = owner || null
    if (status !== t.lifecycle) changes.status = status
    if (due.trim()) changes.due_text = due.trim()
    onSave(changes, t.version)
  }
  const src = t.source_message
  const sender = src ? people.find((p) => p.id === src.sender_id) ?? null : null
  return (
    <div className="space-y-5">
      <div>
        <label className="sr-only" htmlFor="task-title">Title</label>
        <textarea id="task-title" rows={2} value={title} onChange={(e) => setTitle(e.target.value)}
          className="w-full resize-none rounded-lg bg-transparent px-1 text-[22px] font-bold leading-tight outline-none first-letter:uppercase focus:bg-surface" />
        <div className="px-1"><StatusBadge status={t.ui_status} /></div>
      </div>

      <div className="group-list">
        <Row label="Owner">
          <select className={`${bare} appearance-none`} value={owner} onChange={(e) => setOwner(e.target.value)} aria-label="Owner">
            <option value="">Unassigned</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Row>
        <Row label="Status">
          <select className={`${bare} appearance-none`} value={status} onChange={(e) => setStatus(e.target.value)} disabled={next.length === 0} aria-label="Status">
            <option value={t.lifecycle}>{LIFECYCLE_LABEL[t.lifecycle]}</option>
            {next.map((n) => <option key={n} value={n}>{LIFECYCLE_LABEL[n]}</option>)}
          </select>
        </Row>
        <Row label="Due"><span className="text-sm">{formatTemporal(t.due)}</span></Row>
        {t.scheduled && <Row label="Planned"><span className="text-sm">{formatTemporal(t.scheduled)}</span></Row>}
        <Row label="New date"><input className={bare} placeholder="e.g. next Friday" value={due} onChange={(e) => setDue(e.target.value)} aria-label="New due date" /></Row>
      </div>
      {t.pending_changes.due && <p className="rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn">A move to {formatTemporal(t.pending_changes.due.value)} is waiting for {t.pending_changes.due.needs_confirmation_from.map((id) => nameOf(people, id)).join(' or ') || 'confirmation'}. The due date stays as shown until it is confirmed.</p>}

      <div className="flex gap-2">
        <button onClick={save} disabled={!dirty || saving} className="btn btn-primary flex-1">Save changes</button>
        {next.includes('completed') && t.ui_status !== 'blocked' && <button onClick={() => onSave({ status: 'completed' }, t.version)} disabled={saving} className="btn flex-1 bg-ok-bg text-ok hover:bg-ok/15">Mark done</button>}
      </div>
      <p className="-mt-3 px-1 text-xs text-faint">Changes are recorded as {nameOf(people, activeId)}.</p>

      {src && (
        <section aria-label="Source message">
          <h3 className="section-label mb-1.5 px-1">From the chat</h3>
          <div className="group-list p-3">
            <div className="flex items-center gap-2 text-sm"><Avatar person={sender} size={20} /><span className="font-semibold">{nameOf(people, src.sender_id)}</span><span className="text-xs text-faint">{formatTime(src.created_at)}</span></div>
            <p className="mt-1">{src.text}</p>
            <button onClick={() => onInspect(src.id)} aria-label="How the AI read this — open in Inspector" className="mt-2 inline-flex items-center gap-1 text-[13px] font-medium text-accent hover:underline">
              <Sparkles size={13} aria-hidden />How the AI read this
            </button>
          </div>
        </section>
      )}

      <section aria-label="Dependencies">
        <h3 className="section-label mb-1.5 px-1">Dependencies</h3>
        <ul className="group-list">
          {t.edges.length === 0 && <li className="px-3 py-2.5 text-sm text-muted">No confirmed dependencies.</li>}
          {t.edges.map((e) => {
            const other = e.prerequisite === t.id ? e.dependent : e.prerequisite
            return (
              <li key={e.id}>
                <button onClick={() => onOpenTask(other)} className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-fill">
                  <span className="w-16 shrink-0 text-[13px] text-muted">{e.prerequisite === t.id ? 'Blocks' : 'Waits on'}</span>
                  <span className="min-w-0 flex-1 truncate font-medium first-letter:uppercase">{titleOf(other)}</span>
                  {e.kind !== 'accepted' && <span className={`text-xs ${e.kind === 'held' ? 'text-danger' : 'text-faint'}`}>{e.kind === 'held' ? `held · ${e.reason.split(':')[0].toLowerCase()}` : e.kind}</span>}
                  <ChevronRight size={15} className="text-line-strong" aria-hidden />
                </button>
              </li>
            )
          })}
        </ul>
      </section>

      <section aria-label="History">
        <details>
          <summary className="section-label cursor-pointer px-1">Activity ({t.history.length})</summary>
          <ol className="group-list mt-1.5">{t.history.map((h) => <HistoryItem key={h.event_id} h={h} people={people} />)}</ol>
        </details>
      </section>
    </div>
  )
}
