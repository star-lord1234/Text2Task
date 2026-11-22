import { AlertTriangle, CheckCircle2, Circle, CircleDashed, CircleDot, Lock, XCircle, type LucideIcon } from 'lucide-react'
import { STATUS_TEXT } from '../lib/format'

const ICON: Record<string, LucideIcon> = { todo: Circle, in_progress: CircleDot, blocked: Lock, done: CheckCircle2, canceled: XCircle, needs_review: AlertTriangle, proposed: CircleDashed }
const TONE: Record<string, string> = {
  todo: 'text-muted', in_progress: 'text-accent', blocked: 'text-warn', done: 'text-ok', canceled: 'text-faint', needs_review: 'text-warn', proposed: 'text-muted',
}

/** Status is ALWAYS an icon plus a text label, never colour alone. */
export function StatusBadge({ status, extra }: { status: string; extra?: string }) {
  const Icon = ICON[status] ?? Circle
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium ${TONE[status] ?? 'text-muted'}`}>
      <Icon size={14} aria-hidden strokeWidth={2} />
      <span>{STATUS_TEXT[status] ?? status}{extra ? ` ${extra}` : ''}</span>
    </span>
  )
}
