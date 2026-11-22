import * as Dialog from '@radix-ui/react-dialog'
import { useState } from 'react'
import type { Participant, Suggestion, TaskView } from '../../api/types'
import { formatTemporal } from '../../lib/format'

type Props = {
  suggestion: Suggestion | null
  people: Participant[]
  tasks: TaskView[]
  onClose: () => void
  onSubmit: (id: string, edits: Record<string, unknown>) => void
}

export function EditSuggestionDialog({ suggestion: s, people, tasks, onClose, onSubmit }: Props) {
  return (
    <Dialog.Root open={!!s} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content className="enter fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[min(30rem,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl bg-canvas p-4 shadow-[var(--shadow-sheet)] focus:outline-none">
          {s && <Form key={s.id} s={s} people={people} tasks={tasks} onClose={onClose} onSubmit={onSubmit} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label className="flex items-center gap-3 px-3 py-2"><span className="w-20 shrink-0 text-sm text-muted">{label}</span><span className="min-w-0 flex-1">{children}</span></label>
)
const bare = 'w-full bg-transparent py-1 text-right outline-none placeholder:text-faint'

function Form({ s, people, tasks, onClose, onSubmit }: Omit<Props, 'suggestion'> & { s: Suggestion }) {
  const after = (s.after ?? {}) as { title?: string; owner_id?: string | null }
  const isCreate = s.operation === 'CREATE_TASK'
  const isOwner = s.operation === 'UPDATE_ASSIGNEE'
  const isDate = s.operation === 'PROPOSE_DUE_DATE_CHANGE' || s.operation === 'CONFIRM_DUE_DATE_CHANGE'
  // start from what the AI suggested, so saving without touching a field keeps it (it used to reset the owner to "unassigned")
  const initialOwner = isCreate ? after.owner_id ?? '' : typeof s.after === 'string' ? s.after : ''
  const [title, setTitle] = useState(after.title ?? s.summary.match(/“(.+?)”/)?.[1] ?? '')
  const [owner, setOwner] = useState<string>(initialOwner)
  const [dueText, setDueText] = useState('')
  const [taskId, setTaskId] = useState('')
  const needsTask = s.requires_referent
  const candidates = (s.match.ranked ?? []).map((r) => ({ ...r, task: tasks.find((t) => t.id === r.task_id) }))
  const ownerOk = !isOwner || !!owner
  const dateOk = !isDate || !s.unresolved.includes('date') || !!dueText.trim()
  const valid = (!needsTask || !!taskId) && ownerOk && dateOk

  const submit = () => {
    const edits: Record<string, unknown> = {}
    if (needsTask && taskId) edits.task_id = taskId
    if (isCreate) {
      if (title.trim() && title.trim() !== after.title) edits.title = title.trim()
      if (owner !== (after.owner_id ?? '')) edits.owner_id = owner || null
      if (dueText.trim()) edits.due_text = dueText.trim()
    }
    if (isOwner && owner) edits.owner_id = owner
    if (isDate && dueText.trim()) edits.after_raw = dueText.trim()
    onSubmit(s.id, edits)
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); if (valid) submit() }}>
      <div className="mb-3 flex items-center">
        <button type="button" onClick={onClose} className="btn btn-plain -ml-2">Cancel</button>
        <Dialog.Title className="flex-1 text-center text-[17px] font-semibold">{needsTask ? 'Which task?' : 'Edit suggestion'}</Dialog.Title>
        <button type="submit" disabled={!valid} className="btn btn-plain -mr-2 font-semibold">Accept</button>
      </div>
      <Dialog.Description className="sr-only">{s.summary}</Dialog.Description>
      {s.evidence.sentence && <p className="mb-3 px-1 text-[13px] italic text-muted">“{s.evidence.sentence}”</p>}

      {needsTask && (
        <fieldset className="mb-3">
          <legend className="section-label mb-1.5 px-1">They probably mean… (nothing changes until you pick)</legend>
          <div className="group-list">
            {candidates.length === 0 && <p className="px-3 py-2.5 text-sm text-muted">No candidate tasks.</p>}
            {candidates.map((c) => (
              <label key={c.task_id} className="flex cursor-pointer items-center gap-3 px-3 py-2.5 has-[:checked]:bg-accent-bg">
                <input type="radio" name="task" value={c.task_id} checked={taskId === c.task_id} onChange={() => setTaskId(c.task_id)} className="accent-accent" />
                <span className="min-w-0 flex-1 font-medium first-letter:uppercase">{c.task?.title ?? c.task_id}</span>
                <span className="text-xs text-faint" title={Object.entries(c.signals).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(', ')}>match {Math.round(c.score)}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {isCreate && (
        <div className="group-list">
          <Row label="Title"><input className={bare} value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" /></Row>
          <Row label="Owner">
            <select className={`${bare} appearance-none`} value={owner} onChange={(e) => setOwner(e.target.value)} aria-label="Owner">
              <option value="">Unassigned</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Row>
          <Row label="Due"><input className={bare} placeholder={(s.after as any)?.due ? formatTemporal((s.after as any).due) : 'e.g. next Friday'} value={dueText} onChange={(e) => setDueText(e.target.value)} aria-label="Due" /></Row>
        </div>
      )}
      {isOwner && (
        <div className="group-list">
          <Row label="New owner">
            <select className={`${bare} appearance-none`} value={owner} onChange={(e) => setOwner(e.target.value)} aria-label="New owner">
              <option value="" disabled>Choose…</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Row>
        </div>
      )}
      {isDate && (
        <div className="group-list">
          <Row label="New date"><input className={bare} placeholder={s.unresolved.includes('date') ? 'Required, e.g. next Monday' : 'Optional, e.g. 2026-11-16'} value={dueText} onChange={(e) => setDueText(e.target.value)} aria-label="New date" /></Row>
        </div>
      )}
    </form>
  )
}
