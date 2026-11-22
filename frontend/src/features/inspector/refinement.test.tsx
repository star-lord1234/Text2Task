import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { describe, expect, it, vi } from 'vitest'
import type { Entity, RefinementRecord } from '../../api/types'
import { analysis, message, people } from '../../test/fixtures'
import { InspectorDrawer } from './InspectorDrawer'

const TEXT = "I'll send the invoice tomorrow."
const raw: Entity[] = [
  { id: 'pred-e0', type: 'TASK', start: 5, end: 13, text: 'send the', confidence: 0.91 },
  { id: 'pred-e1', type: 'TASK', start: 18, end: 21, text: 'ice', confidence: 0.82 },
  { id: 'pred-e2', type: 'TEMPORAL', start: 22, end: 30, text: 'tomorrow', confidence: 0.9 },
]
const refined: Entity[] = [
  { id: 'pred-e0', type: 'TASK', start: 5, end: 21, text: 'send the invoice', confidence: 0.86, origin: 'refined', neural_ids: ['pred-e0', 'pred-e1'],
    refinement: [{ op: 'merge_adjacent', from: ['send the', 'invoice'], to: 'send the invoice' }] },
  { id: 'rule-t1', type: 'TEMPORAL', start: 22, end: 30, text: 'tomorrow', confidence: null, origin: 'rule', neural_ids: [], refinement: [{ op: 'detect_temporal', to: 'tomorrow', rule: 'regex:DATE' }] },
]
const record = (over: Partial<RefinementRecord> = {}): RefinementRecord => ({
  version: 'refine-v1', config: { preset: 'hybrid', entity_source: 'neural', span_snap: true, clause_dependencies: true, rule_dependency_linker: true },
  raw_entities: raw, entities: refined, rule_relations: [], raw_relations: [{ source_id: 'pred-e0', target_id: 'pred-e2', label: 'SCHEDULED_ON', score: 0.96, provenance: 'neural' }],
  relation_edits: [{ op: 'add_owner', task: 'send the invoice', person: 'Anushree', rule: 'vocative_or_subject_before_task' }], clause_hints: [], clause_dependencies: [], imperative_ids: [],
  trace: [{ step: 'span_snap', action: 'extended', from: 'ice', to: 'invoice' }, { step: 'filter_invalid_tasks', action: 'dropped', text: 'the', reason: 'only function words' }], ...over,
})
const live = (over = {}) => analysis({
  message: message({ text: TEXT, mode: 'live' }), entities: refined, refinement: record(),
  relations: [{ source_id: 'pred-e0', target_id: 'rule-t1', label: 'SCHEDULED_ON', score: 0.97, provenance: 'neural', model_version: 'relations-markers_sqrt', source_text: 'send the invoice', target_text: 'tomorrow' },
              { source_id: 'pred-e0', target_id: 'pred-e9', label: 'DEPENDS_ON', score: null, provenance: 'rule', rule: 'clause:cue_first', cue: 'after', evidence_text: 'After you clean the dataset, write a report.', source_text: 'write a report', target_text: 'clean the dataset' }],
  provenance: { entities: 'neural', entity_refinement: 'rule', relations: 'neural', dependency_links: 'rule', temporal: 'rule', identity: 'rule', reconciliation: 'rule (cue-based)' }, ...over,
})
const open = (a = live()) => render(<InspectorDrawer open analysis={a} loading={false} people={people} onClose={vi.fn()} />)

describe('Inspector separates raw neural, refined and rule output', () => {
  it('labels every span with its origin and explains each repair', () => {
    open()
    const rows = screen.getAllByTestId('entity-row')
    expect(rows.map((r) => r.getAttribute('data-origin'))).toEqual(['refined', 'rule'])
    expect(within(rows[0]).getByText(/Merged “send the” \+ “invoice” into “send the invoice”/)).toBeInTheDocument()
    expect(within(rows[1]).getByText(/Detected by rule, not by the model/)).toBeInTheDocument()
    expect(within(rows[0]).getByTitle(/neural span that rules repaired/)).toBeInTheDocument()
  })

  it('highlights refined and rule spans differently from neural ones and can switch to the raw neural spans', async () => {
    open()
    const marks = () => Array.from(screen.getByTestId('highlighted-text').querySelectorAll('mark')).map((m) => [m.textContent?.split(' (')[0], m.getAttribute('data-origin')])
    expect(marks()).toEqual([['send the invoice', 'refined'], ['tomorrow', 'rule']])
    await userEvent.click(screen.getByRole('radio', { name: 'Raw neural' }))
    expect(marks()).toEqual([['send the', 'neural'], ['ice', 'neural'], ['tomorrow', 'neural']])
    expect(screen.getByRole('radio', { name: 'Raw neural' })).toHaveAttribute('aria-checked', 'true')
    await userEvent.click(screen.getByRole('radio', { name: 'Refined' }))
    expect(marks()[0]).toEqual(['send the invoice', 'refined'])
  })

  it('lists what the rules did, and keeps the raw neural output available', async () => {
    open()
    const trace = screen.getByTestId('refinement-trace')
    expect(within(trace).getByText(/Snap to word boundary/)).toBeInTheDocument()
    expect(within(trace).getByText(/“ice” → “invoice”/)).toBeInTheDocument()
    expect(within(trace).getByText(/only function words/)).toBeInTheDocument()
    await userEvent.click(screen.getByText(/Raw neural output \(3 spans\)/))
    expect(within(screen.getByTestId('raw-entities')).getByText(/“ice”/)).toBeInTheDocument()
  })

  it('shows neural and rule relations in separate groups, with the rule, cue and evidence', async () => {
    open()
    await userEvent.click(screen.getByRole('tab', { name: 'Links' }))
    expect(screen.getByText(/Neural relation model \(on the refined spans\)/)).toBeInTheDocument()
    expect(screen.getByText('Generated by rules')).toBeInTheDocument()
    const rels = screen.getAllByTestId('relation')
    expect(rels.map((r) => r.getAttribute('data-provenance'))).toEqual(['neural', 'rule'])
    expect(within(rels[1]).getByText(/rule: clause:cue_first/)).toBeInTheDocument()
    expect(within(rels[1]).getByText(/cue “after”/)).toBeInTheDocument()
    expect(screen.getByTestId('relation-edits')).toHaveTextContent('Added Anushree as owner of “send the invoice”')
    expect(screen.getByText(/Relations the model gave on the raw spans \(1\)/)).toBeInTheDocument()
  })

  it('shows the pipeline configuration and the span-refinement provenance', async () => {
    open()
    await userEvent.click(screen.getByRole('tab', { name: 'Sources' }))
    expect(screen.getByText('Span refinement')).toBeInTheDocument()
    const cfg = screen.getByTestId('refine-config')
    expect(within(cfg).getByText('Snap spans to word boundaries').nextElementSibling).toHaveTextContent('on')
    expect(within(cfg).getByText('Lifecycle without a task span').nextElementSibling).toHaveTextContent('off')
  })

  it('neural_only: no raw/refined toggle, nothing labelled refined', () => {
    const a = live({ entities: raw, refinement: record({ config: { preset: 'neural_only', entity_source: 'neural' }, entities: raw, trace: [], relation_edits: [], raw_relations: null }) })
    open(a)
    expect(screen.queryByRole('radio', { name: 'Raw neural' })).toBeNull()
    expect(screen.getAllByTestId('entity-row').every((r) => r.getAttribute('data-origin') === 'neural')).toBe(true)
    expect(screen.getByText(/rules left the neural output unchanged/i)).toBeInTheDocument()
  })

  it('scripted analyses have no refinement panels and keep the scripted label', () => {
    open(analysis())
    expect(screen.queryByTestId('refinement-summary')).toBeNull()
    expect(screen.queryByRole('radio', { name: 'Raw neural' })).toBeNull()
  })

  it('has no automatic accessibility violations', async () => {
    open()
    expect(await axe(document.body)).toHaveNoViolations()
  })
})
