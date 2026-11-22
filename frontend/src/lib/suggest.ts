import type { Participant, Suggestion, TaskView, TemporalValue } from '../api/types'
import { formatTemporal, nameOf } from './format'

/** Only the person a suggestion lands on decides it (mirrors views.reviewers on the server, which re-checks). */
export const canDecide = (s: Suggestion, userId: string | null | undefined): boolean =>
  !!userId && (s.reviewer_ids.length === 0 || s.reviewer_ids.includes(userId))

/** The author of the message may also dismiss it, e.g. when the AI misread what they wrote. */
export const canDismiss = (s: Suggestion, userId: string | null | undefined): boolean =>
  canDecide(s, userId) || (!!userId && s.proposer_id === userId)

export function reviewerNames(s: Suggestion, people: Participant[]): string {
  if (s.reviewer_ids.length === 0) return 'anyone'
  return s.reviewer_ids.map((id) => nameOf(people, id)).join(' or ')
}

const isTemporal = (v: unknown): v is TemporalValue => !!v && typeof v === 'object' && 'raw' in (v as object)
const quoted = (s: string) => s.match(/“(.+?)”/)?.[1]

export type SuggestionText = { eyebrow: string; title: string; detail: string | null; action: string }

/** Plain-language card text for a suggestion, written from the point of view of the person reading it. */
export function describeSuggestion(s: Suggestion, tasks: TaskView[], people: Participant[], me: string | null): SuggestionText {
  const task = tasks.find((t) => t.id === s.task_id)
  const taskTitle = task?.title ?? quoted(s.summary) ?? 'a task'
  const you = (id: string | null | undefined) => (id && id === me ? 'you' : nameOf(people, id))
  const after = s.after as Record<string, unknown> | string | null
  switch (s.operation) {
    case 'CREATE_TASK': {
      const a = (after ?? {}) as { title?: string; owner_id?: string | null; due?: TemporalValue | null }
      return {
        eyebrow: a.owner_id ? `New task for ${you(a.owner_id)}` : 'New task · no one assigned yet',
        title: a.title ?? quoted(s.summary) ?? s.summary,
        detail: a.due ? `Due ${formatTemporal(a.due)}` : null,
        action: 'Accept',
      }
    }
    case 'UPDATE_ASSIGNEE':
      return { eyebrow: typeof after === 'string' ? `Hand over to ${you(after)}` : 'Who should own this?', title: taskTitle, detail: null, action: 'Accept' }
    case 'PROPOSE_DUE_DATE_CHANGE':
      return {
        eyebrow: s.direct ? 'New due date' : `Date change requested by ${you(s.proposer_id)}`,
        title: taskTitle,
        detail: isTemporal(after) ? `→ ${formatTemporal(after)}` : 'New date not clear yet',
        action: 'Accept',
      }
    case 'CONFIRM_DUE_DATE_CHANGE':
      return { eyebrow: 'Confirm the new date', title: taskTitle, detail: isTemporal(after) ? `→ ${formatTemporal(after)}` : null, action: 'Accept' }
    case 'COMPLETE_TASK': return { eyebrow: 'Mark as done', title: taskTitle, detail: null, action: 'Accept' }
    case 'CANCEL_TASK': return { eyebrow: 'Cancel this task', title: taskTitle, detail: null, action: 'Accept' }
    case 'UPDATE_STATUS': return { eyebrow: 'Mark as in progress', title: taskTitle, detail: null, action: 'Accept' }
    case 'ADD_DEPENDENCY': {
      const m = /“(.+?)” depends on “(.+?)”/.exec(s.summary)
      return { eyebrow: 'Has to wait for another task', title: m?.[1] ?? taskTitle, detail: m ? `Starts after “${m[2]}”` : null, action: 'Accept' }
    }
    case 'NO_ACTION': return { eyebrow: 'Heads-up', title: s.summary, detail: null, action: 'Got it' }
    default: return { eyebrow: 'Suggestion', title: s.summary, detail: null, action: 'Accept' }
  }
}
