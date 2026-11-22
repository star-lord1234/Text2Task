const STYLE: Record<string, string> = {
  neural: 'bg-accent-bg text-accent',
  rule: 'bg-fill text-muted',
  refined: 'bg-accent-bg text-accent',
  scripted: 'bg-warn-bg text-warn',
  human: 'bg-ok-bg text-ok',
}
const TITLE: Record<string, string> = {
  neural: 'Produced by a trained model (provisional, SILVER-trained)',
  rule: 'Produced by explicit rules, not a trained model',
  refined: 'A neural span that rules repaired (snapped to a word boundary, merged or completed). The raw neural span is kept.',
  scripted: 'Pre-written by the scenario fixture, NOT a model prediction',
  human: 'Entered or corrected by a person',
}

/** Where a value came from. Short label, full explanation on hover. */
export function ProvenanceChip({ kind }: { kind: string }) {
  const base = kind.split(' ')[0]
  return (
    <span title={TITLE[base]} className={`inline-flex items-center rounded-full px-2 py-px text-[11px] font-medium leading-4 ${STYLE[base] ?? STYLE.rule}`}>
      {kind}
    </span>
  )
}
