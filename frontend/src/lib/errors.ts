import { ApiError } from '../api/client'

/** Human wording for API failures. Stale edits and missing prerequisites get specific, actionable text. */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'STALE_VERSION') return 'This task changed since you opened it. Reload and try again.'
    if (e.code === 'PREREQUISITE_PENDING') return 'Accept the related suggestion first (for example the task a dependency refers to).'
    if (e.code === 'UNRESOLVED_VALUE') return 'A required value is unresolved. Edit the suggestion and provide it.'
    if (e.code === 'REFERENT_REQUIRED') return 'Choose which task this refers to before accepting.'
    if (e.code === 'NETWORK') return e.message
    return e.message.replace(/^[A-Z_]+: /, '')
  }
  return e instanceof Error ? e.message : String(e)
}
