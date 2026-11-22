import { render, screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'
import { ModeBanner } from './ModeBanner'
import { ProvenanceChip } from './ProvenanceChip'
import { StatusBadge } from './StatusBadge'
import type { Capabilities } from '../api/types'

const model = { name: 'entity_v2_three_class/epoch3_sqrt_weighted', status: 'loaded', available: true, error: null, provisional: true, provenance: 'SILVER' }
const caps = (over: Partial<Capabilities> = {}): Capabilities => ({
  entity_model: model, relation_model: { ...model, name: 'relation classifier', version: 'relations-markers_sqrt' },
  rule_fallback: { available: true, enabled: false, covers: [], note: '' }, rule_dependency_linker: { enabled: true, note: '' },
  modes: { scripted: true, live: true, live_reason: null }, components: {}, ...over,
  pipeline: { preset: 'hybrid', config: { entity_source: 'neural' }, presets: [{ name: 'hybrid', note: 'All stages', config: {} }, { name: 'neural_only', note: 'Raw', config: {} }] },
})

describe('StatusBadge: status is never colour alone', () => {
  for (const s of ['todo', 'in_progress', 'blocked', 'done', 'canceled', 'needs_review', 'proposed']) {
    it(`${s} renders an icon AND a text label`, () => {
      const { container } = render(<StatusBadge status={s} />)
      expect(container.querySelector('svg')).toBeTruthy()
      expect(container.textContent!.trim().length).toBeGreaterThan(2)
    })
  }
  it('has no accessibility violations', async () => expect(await axe(render(<ul><li><StatusBadge status="blocked" extra="by 1" /></li></ul>).container)).toHaveNoViolations())
})

describe('ModeBanner keeps scripted, live and unavailable visibly different', () => {
  it('scripted says the extraction is pre-written', () => {
    render(<ModeBanner mode="scripted" caps={caps()} />)
    expect(screen.getByTestId('mode-banner')).toHaveAttribute('data-mode', 'scripted')
    expect(screen.getByText(/pre-written/)).toBeInTheDocument()
  })
  it('live names the real models, their provisional status and the fallback state', () => {
    render(<ModeBanner mode="live" caps={caps()} />)
    const b = screen.getByTestId('mode-banner')
    expect(b).toHaveAttribute('data-mode', 'live')
    expect(b).toHaveTextContent(/provisional, SILVER-trained/)
    expect(b).toHaveTextContent('relations-markers_sqrt')
    expect(b).toHaveTextContent('Rule fallback off')
    expect(b).toHaveTextContent('nothing applies until you accept')
  })
  it('live with the opt-in fallback ON says so', () => {
    render(<ModeBanner mode="live" caps={caps({ rule_fallback: { available: true, enabled: true, covers: [], note: '' } })} />)
    expect(screen.getByTestId('mode-banner')).toHaveTextContent('Rule fallback ON')
  })
  it('unavailable models are an alert that says nothing is extracted and scripted is never substituted', () => {
    render(<ModeBanner mode="live" caps={caps({ modes: { scripted: true, live: false, live_reason: 'entity and/or relation model unavailable (rule fallback is off)' } })} />)
    const b = screen.getByRole('alert')
    expect(b).toHaveAttribute('data-mode', 'live-unavailable')
    expect(b).toHaveTextContent('Model unavailable')
    expect(b).toHaveTextContent('never substituted')
  })
  it('has no accessibility violations', async () => expect(await axe(render(<ModeBanner mode="scripted" caps={caps()} />).container)).toHaveNoViolations())
})

describe('ProvenanceChip', () => {
  it('labels each source kind distinctly and explains it', () => {
    render(<><ProvenanceChip kind="neural" /><ProvenanceChip kind="rule" /><ProvenanceChip kind="scripted" /><ProvenanceChip kind="human" /></>)
    for (const k of ['neural', 'rule', 'scripted', 'human']) expect(screen.getByText(k)).toBeInTheDocument()
    expect(screen.getByText('scripted')).toHaveAttribute('title', expect.stringContaining('NOT a model prediction'))
  })
})
