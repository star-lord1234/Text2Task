import { ArrowUp, Clock, Users } from 'lucide-react'
import { useState } from 'react'
import type { Mode, Participant } from '../../api/types'

type Props = {
  people: Participant[]
  active: Participant | null
  mode: Mode
  liveAvailable: boolean
  sending: boolean
  onSend: (b: { text: string; recipient_ids: string[]; created_at?: string }) => void
}

/** Slack-style message box. Recipients and a simulated send time are tucked behind two small toggles. */
export function Composer({ people, active, mode, liveAvailable, sending, onSend }: Props) {
  const [text, setText] = useState('')
  const [when, setWhen] = useState('')
  const [to, setTo] = useState<Record<string, boolean>>({})
  const [panel, setPanel] = useState<'none' | 'to' | 'time'>('none')
  const others = people.filter((p) => p.id !== active?.id)
  const recipients = others.filter((p) => to[p.id] ?? true).map((p) => p.id)
  const disabledReason =
    mode === 'scripted' ? 'Demo story: use Next to send the next scripted message. Switch to Live AI in Settings to type your own.'
      : !liveAvailable ? 'Model unavailable: Live analysis cannot run, so typed messages are disabled.' : null
  const canSend = !disabledReason && !!active && text.trim().length > 0 && !sending
  const toLabel = recipients.length === others.length ? 'Everyone' : recipients.length === 0 ? 'Nobody' : others.filter((p) => recipients.includes(p.id)).map((p) => p.name).join(', ')

  const submit = () => {
    if (!canSend) return
    onSend({ text: text.trim(), recipient_ids: recipients, created_at: when || undefined })
    setText('')
  }
  const chip = (on: boolean) => `inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${on ? 'bg-accent-bg text-accent' : 'text-muted hover:bg-fill'}`

  return (
    <form className="px-3 pb-3 pt-1" onSubmit={(e) => { e.preventDefault(); submit() }} aria-label="Message composer">
      <div className="rounded-xl border border-line-strong bg-surface focus-within:border-faint">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} disabled={!!disabledReason} aria-label={`Message as ${active?.name ?? 'user'}`}
          placeholder={disabledReason ?? `Message #team-chat as ${active?.name ?? '…'}`}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          className="block min-h-14 w-full resize-none rounded-t-xl bg-transparent px-3 pt-2.5 outline-none placeholder:text-faint disabled:text-muted" />
        {panel === 'to' && (
          <fieldset className="flex flex-wrap items-center gap-3 px-3 pb-1 text-sm"><legend className="sr-only">Recipients</legend>
            {others.map((p) => (
              <label key={p.id} className="flex items-center gap-1.5">
                <input type="checkbox" checked={to[p.id] ?? true} onChange={(e) => setTo({ ...to, [p.id]: e.target.checked })} className="accent-accent" />{p.name}
              </label>
            ))}
          </fieldset>
        )}
        {panel === 'time' && (
          <label className="flex items-center gap-2 px-3 pb-1 text-xs text-muted">Pretend it was sent at
            <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} aria-label="Simulated message time" className="rounded-md bg-fill px-2 py-1 text-xs" />
            <span className="text-faint">(empty = now)</span>
          </label>
        )}
        <div className="flex items-center gap-1 px-2 pb-2">
          <button type="button" disabled={!!disabledReason} aria-expanded={panel === 'to'} onClick={() => setPanel(panel === 'to' ? 'none' : 'to')} className={chip(panel === 'to')}><Users size={13} aria-hidden />To: {toLabel}</button>
          <button type="button" disabled={!!disabledReason} aria-expanded={panel === 'time'} onClick={() => setPanel(panel === 'time' ? 'none' : 'time')} className={chip(panel === 'time' || !!when)} aria-label="Message time"><Clock size={13} aria-hidden />{when ? when.replace('T', ' ') : 'Now'}</button>
          <button type="submit" disabled={!canSend} aria-label="Send" className="ml-auto inline-flex h-8 w-8 items-center justify-center rounded-lg bg-ok text-white disabled:bg-line disabled:text-faint"><ArrowUp size={16} aria-hidden /></button>
        </div>
      </div>
    </form>
  )
}
