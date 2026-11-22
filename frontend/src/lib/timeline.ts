import type { TaskView, TemporalValue } from '../api/types'

export type DateKind = 'due' | 'scheduled'
export type DatedTask = { task: TaskView; day: string; kind: DateKind }
export type TimelineRow = { ownerId: string | null; dated: DatedTask[]; undated: TaskView[] }

/** The calendar day of a RESOLVED value ("2026-11-12" or "2026-11-12T14:00..."); a range uses its end. Anything else has no day. */
export function dayOf(v: TemporalValue | null | undefined): string | null {
  if (!v || v.status !== 'RESOLVED') return null
  const raw = v.granularity === 'WEEK' || v.granularity === 'RANGE' ? v.end : v.value ?? v.start
  const m = raw ? /^(\d{4}-\d{2}-\d{2})/.exec(raw) : null
  return m ? m[1] : null
}

/** A task's due day (kept for callers that only care about deadlines). */
export const dueDay = (t: TaskView): string | null => dayOf(t.due)

/** Where a task sits on the timeline: its confirmed due date, else its confirmed scheduled date ("tomorrow", "on Thursday"
 * are read as a planned time rather than a deadline, and used to vanish from the timeline). */
export function placeOf(t: TaskView): { day: string; kind: DateKind } | null {
  const due = dayOf(t.due)
  if (due) return { day: due, kind: 'due' }
  const sched = dayOf(t.scheduled)
  return sched ? { day: sched, kind: 'scheduled' } : null
}

const dayNum = (d: string) => Math.round(Date.parse(`${d}T00:00:00Z`) / 86400000)
export const dayDiff = (a: string, b: string) => dayNum(b) - dayNum(a)
export const addDays = (d: string, n: number) => new Date((dayNum(d) + n) * 86400000).toISOString().slice(0, 10)

/** Rows per owner (people order, then unassigned); closed tasks are excluded. Tasks without a confirmed day are listed, never placed. */
export function buildTimeline(tasks: TaskView[], ownerOrder: string[]) {
  const open = tasks.filter((t) => t.ui_status !== 'done' && t.ui_status !== 'canceled')
  const rows = new Map<string | null, TimelineRow>()
  for (const id of [...ownerOrder, null]) rows.set(id, { ownerId: id, dated: [], undated: [] })
  for (const t of open) {
    const row = rows.get(t.owner_id) ?? rows.set(t.owner_id, { ownerId: t.owner_id, dated: [], undated: [] }).get(t.owner_id)!
    const at = placeOf(t)
    if (at) row.dated.push({ task: t, ...at })
    else row.undated.push(t)
  }
  const list = [...rows.values()].filter((r) => r.dated.length || r.undated.length)
  const days = list.flatMap((r) => r.dated.map((d) => d.day)).sort()
  return { rows: list, first: days[0] ?? null, last: days[days.length - 1] ?? null }
}
