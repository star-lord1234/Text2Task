import type { Participant, TemporalValue } from '../api/types'

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

/** "Thu 12 Nov" for dates; "Thu 12 Nov, 14:00" for datetimes; unresolved values keep their raw text and say why. */
export function formatTemporal(tv: TemporalValue | null | undefined, empty = 'No confirmed due date'): string {
  if (!tv) return empty
  if (tv.status !== 'RESOLVED') return `“${tv.raw}” · ${statusLabel(tv.status)}`
  const v = tv.value ?? tv.start
  if (!v) return tv.raw
  if (tv.granularity === 'WEEK' || tv.granularity === 'RANGE') return `${fmtDay(tv.start!)} – ${fmtDay(tv.end!)}`
  if (tv.granularity === 'MONTH') return new Date(`${tv.start}T00:00:00Z`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })
  if (DATE_ONLY.test(v)) return fmtDay(v) + (tv.part_of_day ? `, ${tv.part_of_day}` : '')
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(v)
  return m ? `${fmtDay(m[1])}, ${m[2]}` : v
}

export function fmtDay(d: string): string {
  const dt = new Date(`${d.slice(0, 10)}T00:00:00Z`)
  return dt.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })
}

export function statusLabel(s: string): string {
  return ({
    UNRESOLVED_NO_ANCHOR: 'needs a reference time', UNRESOLVED_EVENT_CONDITION: 'depends on an event', PARTIAL: 'incomplete', AMBIGUOUS: 'ambiguous',
    VAGUE: 'not a firm date', UNPARSEABLE: 'could not be read',
  } as Record<string, string>)[s] ?? s.toLowerCase().replace(/_/g, ' ')
}

export function formatTime(iso: string): string {
  const m = /T(\d{2}:\d{2})/.exec(iso)
  return m ? m[1] : iso
}

export function nameOf(people: Participant[], id: string | null | undefined): string {
  if (!id) return 'Unassigned'
  return people.find((p) => p.id === id)?.name ?? id
}

export function initials(name: string): string {
  return name.trim().slice(0, 1).toUpperCase()
}

export const STATUS_TEXT: Record<string, string> = {
  todo: 'To do', in_progress: 'In progress', blocked: 'Blocked', done: 'Done', canceled: 'Canceled', needs_review: 'Needs review', proposed: 'Proposed',
}
