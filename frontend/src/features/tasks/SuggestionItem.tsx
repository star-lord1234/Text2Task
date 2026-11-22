import { CircleHelp, Hourglass, Sparkles } from 'lucide-react'
import type { Participant, Suggestion, TaskView } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { ProvenanceChip } from '../../components/ProvenanceChip'
import { describeSuggestion } from '../../lib/suggest'

type Props = {
  s: Suggestion
  busy: boolean
  onAccept: (s: Suggestion, edits?: Record<string, unknown>) => void
  onEdit: (s: Suggestion) => void
  onDismiss: (s: Suggestion) => void
  onSource: (messageId: string) => void
  tasks?: TaskView[]
  people?: Participant[]
  me?: string | null
  /** False when someone else must decide; the card then says who, and shows no Accept. */
  canDecide?: boolean
  /** The author of the message may dismiss a misread even when they cannot accept it. */
  canDismiss?: boolean
  waitingFor?: string
  /** Demo helper: jump to the person who has to decide. */
  onSwitchTo?: () => void
}

const FIELD_LABEL: Record<string, string> = { assignee: 'who owns it', due: 'the due date', date: 'the new date', task: 'which task' }

export function SuggestionItem({ s, busy, onAccept, onEdit, onDismiss, onSource, tasks = [], people = [], me = null, canDecide = true, canDismiss = canDecide, waitingFor, onSwitchTo }: Props) {
  const text = describeSuggestion(s, tasks, people, me)
  const waiting = s.must_accept_first.length > 0
  // a new task nobody was named for: the viewer can take it or leave it open for a volunteer, no Edit round-trip needed
  const openTask = s.operation === 'CREATE_TASK' && s.unresolved.includes('assignee') && !s.requires_referent
  const needsEdit = s.unresolved.some((u) => (u === 'assignee' && !openTask) || u === 'task' || u === 'date')
  const isAck = s.operation === 'NO_ACTION'
  const warnFlags = s.flags.filter((f) => f.severity !== 'info')
  const acceptDisabled = busy || waiting || needsEdit
  const why = waiting ? 'Accept the related suggestion first' : needsEdit ? `Choose ${s.unresolved.map((u) => FIELD_LABEL[u] ?? u).join(' and ')} with Edit first` : ''
  const author = people.find((p) => p.id === s.proposer_id) ?? null
  const eyebrow = s.requires_referent ? 'Which task do they mean?' : text.eyebrow

  return (
    <li className={`enter card list-none p-3.5 ${canDecide ? '' : 'bg-fill/50 shadow-none'}`} data-testid={`suggestion-${s.id}`}>
      <div className="flex items-center gap-1.5 text-[13px]">
        {s.requires_referent ? <CircleHelp size={14} className="text-warn" aria-hidden /> : <Sparkles size={14} className="text-accent" aria-hidden />}
        <span className={`font-semibold ${s.requires_referent ? 'text-warn' : 'text-accent'}`}>{eyebrow}</span>
        <span className="ml-auto"><ProvenanceChip kind={s.source_kind} /></span>
      </div>
      <p className="mt-1 text-[15px] font-semibold leading-snug first-letter:uppercase">{text.title}</p>
      {text.detail && <p className="text-[13px] text-muted">{text.detail}</p>}

      {warnFlags.length > 0 && (
        <ul className="mt-2 space-y-1" aria-label="Open questions">
          {warnFlags.map((f) => <li key={f.code + f.field} className="rounded-lg bg-warn-bg px-2.5 py-1.5 text-[13px] text-warn" title={f.message}>{f.question ?? f.message}</li>)}
        </ul>
      )}

      {s.evidence.sentence && (
        <button onClick={() => onSource(s.message_id)} className="mt-2 flex w-full items-start gap-2 text-left text-[13px] text-muted hover:text-ink" aria-label="Show the message this came from">
          {author && <Avatar person={author} size={18} />}
          <span className="line-clamp-2 italic">“{s.evidence.sentence}”</span>
        </button>
      )}

      {waiting && <p className="mt-2 text-xs text-faint">Waiting for another suggestion to be accepted first.</p>}
      {canDecide && !waiting && needsEdit && <p className="mt-2 text-xs text-faint">{why}.</p>}

      {canDecide ? (
        <div className="mt-3 flex items-center gap-2">
          {openTask && me ? (
            <>
              <button onClick={() => onAccept(s, { owner_id: me })} disabled={acceptDisabled} className="btn btn-primary btn-sm">I'll take it</button>
              <button onClick={() => onAccept(s)} disabled={acceptDisabled} title="Add it without an owner; a teammate can volunteer in the chat" className="btn btn-tinted btn-sm">Leave open</button>
            </>
          ) : <button onClick={() => onAccept(s)} disabled={acceptDisabled} title={why} className="btn btn-primary btn-sm">{isAck ? 'Got it' : text.action}</button>}
          {!isAck && <button onClick={() => onEdit(s)} disabled={busy} className={`btn btn-sm ${openTask && me ? 'btn-plain' : 'btn-tinted'}`}>Edit</button>}
          <button onClick={() => onDismiss(s)} disabled={busy} className="btn btn-plain btn-sm ml-auto text-muted">Dismiss</button>
        </div>
      ) : (
        <div className="mt-2.5 flex items-center gap-2 text-xs text-muted">
          <Hourglass size={13} aria-hidden /><span>Waiting for {waitingFor ?? 'a teammate'} to accept</span>
          <span className="ml-auto flex items-center">
            {canDismiss && <button onClick={() => onDismiss(s)} disabled={busy} className="btn btn-plain btn-sm text-muted" title="You wrote this message: dismiss it if the AI misread you">Dismiss</button>}
            {onSwitchTo && <button onClick={onSwitchTo} className="btn btn-plain btn-sm">Switch to {waitingFor}</button>}
          </span>
        </div>
      )}
    </li>
  )
}
