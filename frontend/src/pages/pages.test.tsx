import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EvaluationPage } from './EvaluationPage'

const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
afterEach(() => vi.restoreAllMocks())

const data = {
  provenance: 'SILVER', statement: 'No human-verified GOLD evaluation exists.', sources: ['results/a.json'], missing: ['phase6 report'],
  entities: { available: true, model: 'DistilBERT', metric: 'seqeval', overall: { precision: 0.12, recall: 0.13, f1: 0.127 }, per_type: { TASK: { precision: 0.005, recall: 0.004, f1: 0.004, support: 272 } }, note: 'not comparable' },
  relations: { available: false },
  phases: [{ id: 'phase6', title: 'Dependency graph', available: false }],
}

describe('EvaluationPage', () => {
  it('shows saved numbers verbatim, the SILVER statement, and what is missing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(data), { status: 200, headers: { 'content-type': 'application/json' } }))
    wrap(<EvaluationPage />)
    expect(await screen.findByText(/No human-verified GOLD/)).toBeInTheDocument()
    expect(screen.getByText('0.127')).toBeInTheDocument()
    expect(screen.getByText(/No saved relation metrics/)).toBeInTheDocument()
    expect(screen.getByText(/Missing: phase6 report/)).toBeInTheDocument()
  })
})
