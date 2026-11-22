import { describe, expect, it } from 'vitest'
import type { TaskView, TemporalValue } from '../api/types'
import { addDays, buildTimeline, dayDiff, dueDay } from './timeline'

const tv = (o: Partial<TemporalValue>): TemporalValue => ({ raw: 'x', status: 'RESOLVED', granularity: 'DAY', start: null, end: null, value: null, assumptions: [], ...o })
const task = (id: string, owner: string | null, due: TemporalValue | null, ui = 'todo', scheduled: TemporalValue | null = null): TaskView => ({ id, title: id, owner_id: owner, ui_status: ui, due, scheduled } as unknown as TaskView)

describe('timeline', () => {
  it('uses only resolved dates; unresolved or missing are listed as undated, never placed', () => {
    expect(dueDay(task('a', 'x', tv({ value: '2026-11-12' })))).toBe('2026-11-12')
    expect(dueDay(task('a', 'x', tv({ value: '2026-11-12T14:00:00-06:00' })))).toBe('2026-11-12')
    expect(dueDay(task('a', 'x', tv({ status: 'UNRESOLVED_NO_ANCHOR', value: null })))).toBeNull()
    expect(dueDay(task('a', 'x', tv({ status: 'AMBIGUOUS', value: '2026-11-12' })))).toBeNull()
    expect(dueDay(task('a', 'x', null))).toBeNull()
  })
  it('a week deadline sits on its last day', () => {
    expect(dueDay(task('a', 'x', tv({ granularity: 'WEEK', start: '2026-11-09', end: '2026-11-15' })))).toBe('2026-11-15')
  })
  it('groups by owner in people order, drops closed tasks, handles zero tasks', () => {
    const r = buildTimeline([task('1', 'b', tv({ value: '2026-11-13' })), task('2', 'a', null), task('3', null, null), task('4', 'a', tv({ value: '2026-11-12' }), 'done')], ['a', 'b'])
    expect(r.rows.map((x) => x.ownerId)).toEqual(['a', 'b', null])
    expect(r.rows[0].dated).toHaveLength(0)
    expect(r.rows[0].undated.map((t) => t.id)).toEqual(['2'])
    expect(r.first).toBe('2026-11-13')
    expect(buildTimeline([], ['a'])).toEqual({ rows: [], first: null, last: null })
  })
  it('a task with only a planned date ("tomorrow", "on Thursday") is placed, marked as scheduled; a deadline wins', () => {
    const r = buildTimeline([task('s', 'a', null, 'todo', tv({ value: '2026-11-12' })), task('d', 'a', tv({ value: '2026-11-13' }), 'todo', tv({ value: '2026-11-12' }))], ['a'])
    expect(r.rows[0].dated.map((x) => [x.task.id, x.day, x.kind])).toEqual([['s', '2026-11-12', 'scheduled'], ['d', '2026-11-13', 'due']])
    expect(r.rows[0].undated).toEqual([])
  })
  it('day arithmetic is calendar based', () => {
    expect(dayDiff('2026-11-12', '2026-11-15')).toBe(3)
    expect(addDays('2026-11-30', 1)).toBe('2026-12-01')
  })
})
