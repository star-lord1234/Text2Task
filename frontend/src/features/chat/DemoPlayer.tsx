import { ChevronLeft, FastForward, Play, RotateCcw } from 'lucide-react'
import type { Participant, ScenarioInfo, ScenarioState } from '../../api/types'
import { Avatar } from '../../components/Avatar'

type Props = {
  scenario: ScenarioState | undefined
  scenarios: ScenarioInfo[]
  people: Participant[]
  busy: boolean
  onLoad: (id: string) => void
  onPrev: () => void
  onNext: () => void
  onPlay: () => void
  onRestart: () => void
}

const short = (title: string | null | undefined) => (title ?? '').replace(/^Scenario \w+ — /, '')

/** Demo mode's stand-in for the composer: shows who speaks next and steps the story forward. */
export function DemoPlayer({ scenario, scenarios, people, busy, onLoad, onPrev, onNext, onPlay, onRestart }: Props) {
  const loaded = !!scenario?.scenario_id
  if (!loaded) {
    return (
      <div className="border-t border-line p-3" aria-label="Scenario controls">
        <p className="mb-2 px-1 text-sm font-medium">Pick a demo story to start</p>
        <div className="flex flex-wrap gap-2">
          {scenarios.map((s) => <button key={s.id} disabled={busy} onClick={() => onLoad(s.id)} className="btn btn-tinted btn-sm">{short(s.title)}</button>)}
        </div>
      </div>
    )
  }
  const s = scenario!
  const finished = s.step >= (s.total ?? 0)
  const next = s.next_message
  const speaker = people.find((p) => p.name.toLowerCase() === next?.sender.toLowerCase() || p.id === next?.sender) ?? null
  return (
    <div className="border-t border-line p-3" aria-label="Scenario controls">
      <div className="mb-2 flex items-center gap-2 px-1 text-xs text-faint">
        <span className="truncate font-semibold text-muted">{short(s.title)}</span>
        <span data-testid="scenario-step" className="whitespace-nowrap">Step {s.step} of {s.total}</span>
        <div className="ml-auto flex gap-1" aria-hidden>{Array.from({ length: s.total ?? 0 }, (_, i) => <span key={i} className={`h-1.5 w-4 rounded-full ${i < s.step ? 'bg-accent' : 'bg-line-strong'}`} />)}</div>
      </div>
      {next && !finished ? (
        <div className="mb-2.5 flex items-start gap-2.5 rounded-xl bg-fill px-3 py-2" data-testid="next-message">
          <Avatar person={speaker} size={22} />
          <p className="min-w-0 flex-1 text-sm text-muted"><span className="font-semibold text-ink">{speaker?.name ?? next.sender}</span> will say: “{next.text}”</p>
        </div>
      ) : <p className="mb-2.5 rounded-xl bg-fill px-3 py-2 text-sm text-muted">That's the end of this story.</p>}
      <div className="flex items-center gap-2">
        <button className="btn btn-gray" aria-label="Previous" title="Previous step" disabled={busy || s.step === 0} onClick={onPrev}><ChevronLeft size={16} aria-hidden /></button>
        {!finished
          ? <button className="btn btn-primary flex-1" disabled={busy} onClick={onNext}><Play size={14} aria-hidden fill="currentColor" />Next</button>
          : <button className="btn btn-primary flex-1" disabled={busy} onClick={onRestart}><RotateCcw size={14} aria-hidden />Restart story</button>}
        {!finished && <button className="btn btn-gray" disabled={busy} onClick={onPlay} title="Plays every remaining message and accepts each suggestion as a clearly labelled simulated reviewer"><FastForward size={15} aria-hidden />Play all</button>}
        {!finished && s.step > 0 && <button className="btn btn-gray" aria-label="Reset scenario" title="Back to the start" disabled={busy} onClick={onRestart}><RotateCcw size={15} aria-hidden /></button>}
      </div>
    </div>
  )
}
