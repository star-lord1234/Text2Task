import { Hash, MessagesSquare } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import type { MessageView, Participant, TaskView } from '../../api/types'
import { Avatar } from '../../components/Avatar'
import { MessageBubble } from './MessageBubble'

type Props = {
  messages: MessageView[]
  people: Participant[]
  tasks?: TaskView[]
  retrying: boolean
  onRetry: (id: string) => void
  onInspect: (id: string) => void
  /** Mode pill shown in the channel header. */
  badge?: ReactNode
  /** Composer (live) or demo player (scripted). */
  footer: ReactNode
}

export function ChatPanel({ messages, people, tasks, retrying, onRetry, onInspect, badge, footer }: Props) {
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }) }, [messages.length])
  return (
    <section aria-label="Team chat" className="flex min-h-0 flex-1 flex-col bg-surface">
      <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
        <h2 className="flex items-center gap-1 text-[17px] font-bold"><Hash size={17} aria-hidden className="text-muted" />team-chat</h2>
        <div className="flex -space-x-1.5" aria-label={`${people.length} members`}>
          {people.map((p) => <span key={p.id} className="rounded-[8px] ring-2 ring-surface" title={p.name}><Avatar person={p} size={22} /></span>)}
        </div>
        <div className="ml-auto">{badge}</div>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto py-3">
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
            <MessagesSquare size={36} className="text-line-strong" aria-hidden />
            <p className="font-semibold">No messages yet</p>
            <p className="max-w-xs text-sm text-muted">As people chat, Text2Task spots requests and turns them into tasks for the right person to accept.</p>
          </div>
        )}
        {messages.map((m) => <MessageBubble key={m.id} message={m} people={people} onInspect={onInspect} onRetry={onRetry} retrying={retrying} tasks={tasks} />)}
        <div ref={end} />
      </div>
      {footer}
    </section>
  )
}
