import { describe, expect, it } from 'vitest'
import { fmtDay, formatTemporal, formatTime, initials, nameOf, statusLabel } from './format'
import { people, resolved } from '../test/fixtures'

describe('formatTemporal', () => {
  it('formats a resolved date without inventing a time', () => expect(formatTemporal(resolved('2026-11-12'))).toBe('Thu 12 Nov'))
  it('formats a datetime', () => expect(formatTemporal({ ...resolved('2026-11-16T10:00:00-06:00'), granularity: 'DATETIME' })).toBe('Mon 16 Nov, 10:00'))
  it('keeps the raw text and says WHY when unresolved', () => {
    const tv = { ...resolved('x'), raw: 'next Friday', status: 'UNRESOLVED_NO_ANCHOR', value: null, start: null, end: null }
    expect(formatTemporal(tv)).toBe('“next Friday” · needs a reference time')
  })
  it('event conditions and vague dates are not shown as dates', () => {
    expect(formatTemporal({ ...resolved('x'), raw: 'after approval', status: 'UNRESOLVED_EVENT_CONDITION', value: null })).toContain('depends on an event')
    expect(formatTemporal({ ...resolved('x'), raw: 'soon', status: 'VAGUE', value: null })).toContain('not a firm date')
  })
  it('handles empty values and ranges', () => {
    expect(formatTemporal(null)).toBe('No confirmed due date')
    expect(formatTemporal(undefined, 'n/a')).toBe('n/a')
    expect(formatTemporal({ ...resolved('2026-11-16'), granularity: 'WEEK', start: '2026-11-16', end: '2026-11-22' })).toBe('Mon 16 Nov – Sun 22 Nov')
  })
  it('does not shift dates across timezones', () => expect(fmtDay('2026-03-01')).toBe('Sun 1 Mar'))
})

describe('small helpers', () => {
  it('status labels, time, names and initials', () => {
    expect(statusLabel('UNRESOLVED_NO_ANCHOR')).toBe('needs a reference time')
    expect(statusLabel('SOMETHING_NEW')).toBe('something new')
    expect(formatTime('2026-11-11T09:30:00-06:00')).toBe('09:30')
    expect(nameOf(people, 'bianca')).toBe('Bianca')
    expect(nameOf(people, null)).toBe('Unassigned')
    expect(nameOf(people, 'ghost')).toBe('ghost')
    expect(initials('  anushree')).toBe('A')
  })
})
