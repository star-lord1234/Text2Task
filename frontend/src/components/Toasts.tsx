import { X } from 'lucide-react'
import { useUI } from '../state/ui'

export function Toasts() {
  const { toasts, dismissToast } = useUI()
  return (
    <div aria-live="polite" role="status" className="pointer-events-none fixed inset-x-0 bottom-6 z-[60] flex flex-col items-center gap-2 px-4">
      {toasts.map((t) => (
        <div key={t.id} className={`enter pointer-events-auto flex max-w-md items-start gap-3 rounded-2xl px-4 py-2.5 text-sm text-white shadow-[var(--shadow-sheet)] ${t.tone === 'error' ? 'bg-danger' : 'bg-ink/90 backdrop-blur'}`}>
          <span className="flex-1">{t.text}</span>
          <button aria-label="Dismiss message" onClick={() => dismissToast(t.id)} className="mt-0.5 text-white/70 hover:text-white"><X size={14} /></button>
        </div>
      ))}
    </div>
  )
}
