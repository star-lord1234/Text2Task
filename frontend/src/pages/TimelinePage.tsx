import { Flag, Lock } from 'lucide-react'
import { useMemo } from 'react'
import { useWorkspace } from '../api/hooks'
import type { TaskView } from '../api/types'
import { Avatar } from '../components/Avatar'
import { formatTemporal, nameOf } from '../lib/format'
import { addDays, buildTimeline, dayDiff, type DateKind } from '../lib/timeline'
import { useUI } from '../state/ui'

const weekday = (d: string) => new Date(`${d}T00:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' })
const dayNum = (d: string) => new Date(`${d}T00:00:00Z`).getUTCDate()
const weekend = (d: string) => [0, 6].includes(new Date(`${d}T00:00:00Z`).getUTCDay())

/** People down the side, days across the top: every open task sits in the cell of its date, so nothing overlaps or gets clipped. */
export function TimelinePage() {
  const ws = useWorkspace()
  const ui = useUI()
  const people = ws.data?.participants ?? []
  const tl = useMemo(() => buildTimeline(ws.data?.tasks ?? [], people.map((p) => p.id)), [ws.data, people])

  const header = (
    <div className="flex items-center gap-3 border-b border-line bg-surface px-4 py-2.5">
      <h1 className="text-[17px] font-bold">Timeline</h1>
      <span className="hidden text-[13px] text-muted sm:inline">Who has what, and when</span>
    </div>
  )
  if (ws.isLoading) return <p className="p-6 text-sm text-muted">Loading…</p>
  if (!tl.rows.length) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">{header}
        <div className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-center"><p className="font-semibold">Nothing scheduled yet</p><p className="text-sm text-muted">Open tasks show up here once they are accepted.</p></div>
      </div>
    )
  }
  const first = tl.first ?? ''
  const days = first ? Array.from({ length: Math.max(7, dayDiff(first, tl.last!) + 1) }, (_, i) => addDays(first, i)) : []
  const anyUndated = tl.rows.some((r) => r.undated.length)
  const person = (id: string | null) => people.find((p) => p.id === id) ?? null
  const cols = `9.5rem${anyUndated ? ' minmax(9.5rem, 1fr)' : ''} repeat(${days.length}, minmax(8.5rem, 1fr))`

  const Chip = ({ t, kind }: { t: TaskView; kind?: DateKind }) => {
    const owner = person(t.owner_id)
    const blocked = t.ui_status === 'blocked' || t.ui_status === 'needs_review'
    const when = kind === 'scheduled' ? `Planned ${formatTemporal(t.scheduled)}` : kind === 'due' ? `Due ${formatTemporal(t.due)}` : 'No confirmed date'
    return (
      <button type="button" onClick={() => ui.openTask(t.id)} title={`${t.title} · ${when}${blocked ? ' · waiting on another task' : ''}`}
        className="w-full rounded-lg border border-line border-l-4 bg-surface px-2 py-1 text-left text-xs shadow-[var(--shadow-card)] hover:bg-fill"
        style={{ borderLeftColor: owner?.color ?? 'var(--color-line-strong)' }}>
        <span className="line-clamp-2 font-medium first-letter:uppercase">{t.title}</span>
        <span className="mt-0.5 flex items-center gap-1 text-[11px] text-muted">
          {kind === 'due' && <Flag size={10} aria-hidden />}{kind === 'due' ? 'Due' : kind === 'scheduled' ? 'Planned' : ''}
          {blocked && <span className="ml-auto inline-flex items-center gap-0.5 text-warn"><Lock size={10} aria-hidden />waiting</span>}
        </span>
      </button>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {header}
      <div className="scroll-thin min-h-0 flex-1 overflow-auto bg-canvas p-4">
        <p className="mb-3 px-1 text-[13px] text-muted">
          Open tasks on their confirmed date ({ws.data?.settings.timezone} time). <Flag size={11} className="inline" aria-hidden /> Due = a deadline; Planned = a time it is meant to happen.
        </p>
        <div className="grid min-w-max overflow-hidden rounded-2xl border border-line bg-surface" style={{ gridTemplateColumns: cols }} role="table" aria-label="Timeline">
          <div role="row" className="contents">
            <div role="columnheader" className="sticky left-0 z-10 border-b border-line bg-surface px-3 py-2 text-xs font-semibold text-faint">Person</div>
            {anyUndated && <div role="columnheader" className="flex items-end justify-center border-b border-l border-line bg-fill/40 px-2 py-2 text-xs font-semibold text-faint">No date yet</div>}
            {days.map((d) => (
              <div key={d} role="columnheader" className={`border-b border-l border-line px-2 py-2 text-center ${weekend(d) ? 'bg-fill/60' : ''}`}>
                <div className="text-[11px] font-semibold uppercase text-faint">{weekday(d)}</div>
                <div className="text-[15px] font-semibold">{dayNum(d)}</div>
              </div>
            ))}
          </div>
          {tl.rows.map((r) => (
            <div role="row" key={r.ownerId ?? 'none'} className="contents">
              <div role="rowheader" className="sticky left-0 z-10 flex items-start gap-2 border-b border-line bg-surface px-3 py-3 text-sm font-medium">
                <Avatar person={person(r.ownerId)} size={20} />{r.ownerId ? nameOf(people, r.ownerId) : 'Unassigned'}
              </div>
              {anyUndated && <div role="cell" className="space-y-1.5 border-b border-l border-line bg-fill/40 p-1.5">{r.undated.map((t) => <Chip key={t.id} t={t} />)}</div>}
              {days.map((d) => (
                <div role="cell" key={d} className={`space-y-1.5 border-b border-l border-line p-1.5 ${weekend(d) ? 'bg-fill/60' : ''}`}>
                  {r.dated.filter((x) => x.day === d).map((x) => <Chip key={x.task.id} t={x.task} kind={x.kind} />)}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
