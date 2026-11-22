import { ChevronDown } from 'lucide-react'
import type { Capabilities, Mode } from '../api/types'

const pill = 'inline-flex cursor-pointer list-none items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold [&::-webkit-details-marker]:hidden'
const pop = 'absolute right-0 top-full z-30 mt-2 w-72 rounded-xl border border-line bg-surface p-3 text-xs leading-relaxed text-muted shadow-[var(--shadow-sheet)]'
const dot = (c: string) => <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${c}`} />

/** A small pill that says which kind of output the screen shows; the details sit one click away. */
export function ModeBanner({ mode, caps }: { mode: Mode; caps: Capabilities | undefined }) {
  if (mode === 'scripted') {
    return (
      <div role="status" data-testid="mode-banner" data-mode="scripted" className="relative"><details>
        <summary className={`${pill} bg-warn-bg text-warn`}>{dot('bg-warn')}Demo story<ChevronDown size={12} aria-hidden /></summary>
        <div className={pop}>
          <p><strong className="text-ink">Demo story.</strong> What the AI picks out of each message is pre-written by the story. Everything after that (suggestions, approvals, history, dependencies) is the real app.</p>
        </div>
      </details></div>
    )
  }
  if (!caps) return <span role="status" data-testid="mode-banner" data-mode="live" className={`${pill} bg-fill text-muted`}>Checking AI…</span>
  if (!caps.modes.live) {
    return (
      <div role="alert" data-testid="mode-banner" data-mode="live-unavailable" className="relative"><details>
        <summary className={`${pill} bg-danger-bg text-danger`}>{dot('bg-danger')}Model unavailable<ChevronDown size={12} aria-hidden /></summary>
        <div className={pop}>
          <p>{caps.modes.live_reason ?? 'Live analysis cannot run.'}</p>
          <p className="mt-1">Messages are saved but nothing is extracted. Demo output is never substituted.</p>
        </div>
      </details></div>
    )
  }
  const e = caps.entity_model, r = caps.relation_model
  const ruleOnly = caps.pipeline.config.entity_source === 'rule'
  return (
    <div role="status" data-testid="mode-banner" data-mode="live" className="relative"><details>
      <summary className={`${pill} bg-ok-bg text-ok`}>{dot('bg-ok')}{ruleOnly ? 'Live · rules only' : 'Live AI'}<ChevronDown size={12} aria-hidden /></summary>
      <div className={pop}>
        {ruleOnly
          ? <p><strong className="text-ink">Rule-based pipeline.</strong> No neural model is used; every output is labelled <em>rule</em>.</p>
          : <p><strong className="text-ink">Real models</strong> (provisional, SILVER-trained): entities {e.available ? e.name.split('/').pop() : 'rule baseline'} · relations {r.version ?? (r.available ? r.name : 'rule linker')}.</p>}
        <p className="mt-1">Pipeline: <strong className="text-ink">{caps.pipeline.preset.replace(/_/g, ' ')}</strong> · {caps.rule_fallback.enabled ? <strong className="text-ink">Rule fallback ON</strong> : 'Rule fallback off'}.</p>
        <p className="mt-1">Review mode: nothing applies until you accept it.</p>
      </div>
    </details></div>
  )
}
