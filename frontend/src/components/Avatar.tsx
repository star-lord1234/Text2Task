import type { Participant } from '../api/types'

/** Slack-style rounded-square avatar with the person's initial. */
export function Avatar({ person, size = 24 }: { person: Pick<Participant, 'name' | 'color'> | null; size?: number }) {
  const radius = Math.round(size * 0.28)
  if (!person) {
    return <span aria-hidden className="inline-flex shrink-0 items-center justify-center border border-dashed border-line-strong text-faint" style={{ width: size, height: size, borderRadius: radius, fontSize: size * 0.5 }}>?</span>
  }
  return (
    <span aria-hidden className="inline-flex shrink-0 items-center justify-center font-semibold text-white"
      style={{ width: size, height: size, borderRadius: radius, background: person.color, fontSize: size * 0.46 }}>
      {person.name.trim().slice(0, 1).toUpperCase()}
    </span>
  )
}
