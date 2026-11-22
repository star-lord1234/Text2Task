import { Check, RotateCw, Sparkles } from 'lucide-react'
import type { MessageView, Participant, TaskView } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { formatTime, nameOf } from '../../lib/format'

type Props = {
  message: MessageView
  people: Participant[]
  onInspect: (id: string) => void
  onRetry: (id: string) => void
  retrying?: boolean
  tasks?: TaskView[]
}

const chip = 'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium'

/** One Slack-style message row. Under it, at most a line of quiet status chips about what the AI found. */
export function MessageBubble({ message: m, people, onInspect, onRetry, retrying, tasks = [] }: Props) {
  const titled = (t: string) => t.replace(/\bT-\d+\b/g, (id) => { const x = tasks.find((k) => k.id === id); return x ? `“${x.title}”` : id })
  const sender = people.find((p) => p.id === m.sender_id) ?? null
  const to = m.recipient_ids.map((r) => nameOf(people, r)).join(', ')
  return (
    <article className="enter group relative flex gap-3 px-4 py-1.5 hover:bg-fill/60" aria-label={`${nameOf(people, m.sender_id)} at ${formatTime(m.created_at)}`} data-testid={`message-${m.id}`}>
      <Avatar person={sender} size={36} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-bold">{nameOf(people, m.sender_id)}</span>
          <span className="text-xs text-faint">{formatTime(m.created_at)}</span>
          {to && <span className="truncate text-xs text-faint">→ {to}</span>}
        </div>
        <p className="whitespace-pre-wrap leading-snug">{m.text}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 empty:hidden">
          {m.status === 'analysis_failed' && (
            <>
              <span role="alert" className={`${chip} bg-danger-bg text-danger`}>Analysis failed · {m.error}</span>
              <button onClick={() => onRetry(m.id)} disabled={retrying} className={`${chip} bg-fill text-ink hover:bg-line`}><RotateCw size={12} aria-hidden />Retry</button>
            </>
          )}
          {m.status === 'no_extraction' && <span className={`${chip} bg-fill text-muted`}>Not analysed · {m.error ?? 'no scripted extraction'}</span>}
          {m.status === 'analysed' && m.pending_count > 0 && <span className={`${chip} bg-warn-bg text-warn`}><Sparkles size={12} aria-hidden />{m.pending_count} {m.pending_count === 1 ? 'suggestion' : 'suggestions'} to review</span>}
          {m.status === 'analysed' && m.applied_count > 0 && <span className={`${chip} bg-ok-bg text-ok`}><Check size={12} aria-hidden />{m.applied_count} accepted</span>}
          {m.status === 'analysed' && m.no_change.map((raw) => { const t = titled(raw); return <span key={raw} className={`${chip} max-w-full truncate bg-fill text-muted`} title={t}>No change · {t.length > 48 ? `${t.slice(0, 48)}…` : t}</span> })}
          {m.matches_expectation === false && <span className={`${chip} bg-warn-bg text-warn`} title={m.expected?.note}>Differs from the scripted expectation</span>}
        </div>
      </div>
      <button onClick={() => onInspect(m.id)} aria-label={`Inspect message from ${nameOf(people, m.sender_id)}`} title="How the AI read this message"
        className="absolute right-3 top-1 inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2 py-1 text-xs font-medium text-muted opacity-0 shadow-[var(--shadow-card)] hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 max-md:opacity-100">
        <Sparkles size={13} aria-hidden /><span className="max-md:sr-only">How AI read this</span>
      </button>
    </article>
  )
}
