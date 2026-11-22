import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Composer } from './chat/Composer'
import { MessageBubble } from './chat/MessageBubble'
import { GraphTable } from './graph/GraphTable'
import { WhatIfPanel } from './graph/WhatIfPanel'
import { InspectorDrawer } from './inspector/InspectorDrawer'
import { EditSuggestionDialog } from './tasks/EditSuggestionDialog'
import { SuggestionItem } from './tasks/SuggestionItem'
import { TaskPanel } from './tasks/TaskPanel'
import { TaskDetails } from './tasks/TaskDetails'
import { analysis, edge, graph, graphNode, message, people, resolved, suggestion, task, taskDetail } from '../test/fixtures'

afterEach(() => vi.restoreAllMocks())
const riya = people[0]

describe('Composer', () => {
  const base = { people, active: riya, sending: false, onSend: vi.fn() }
  it('is disabled in scripted mode and explains why', () => {
    render(<Composer {...base} mode="scripted" liveAvailable />)
    expect(screen.getByLabelText(/Message as Riya/)).toBeDisabled()
    expect(screen.getByPlaceholderText(/use Next to send the next scripted message/)).toBeInTheDocument()
  })
  it('is disabled when the live models are unavailable', () => {
    render(<Composer {...base} mode="live" liveAvailable={false} />)
    expect(screen.getByLabelText(/Message as Riya/)).toBeDisabled()
    expect(screen.getByPlaceholderText(/Model unavailable/)).toBeInTheDocument()
  })
  it('sends on Enter with the chosen recipients and simulated time, and clears', async () => {
    const onSend = vi.fn()
    render(<Composer {...base} onSend={onSend} mode="live" liveAvailable />)
    await userEvent.click(screen.getByRole('button', { name: /To: Everyone/ }))             // recipients are tucked away until asked for
    await userEvent.click(screen.getByRole('checkbox', { name: 'Bianca' }))                 // untick Bianca
    expect(screen.getByRole('button', { name: /To: Anushree/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Message time' }))
    await userEvent.type(screen.getByLabelText('Simulated message time'), '2026-11-11T09:30')
    await userEvent.type(screen.getByLabelText(/Message as Riya/), 'Anushree, please prepare it{Enter}')
    expect(onSend).toHaveBeenCalledWith({ text: 'Anushree, please prepare it', recipient_ids: ['anushree'], created_at: '2026-11-11T09:30' })
    expect(screen.getByLabelText(/Message as Riya/)).toHaveValue('')
  })
  it('does not send empty or whitespace messages', async () => {
    const onSend = vi.fn()
    render(<Composer {...base} onSend={onSend} mode="live" liveAvailable />)
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Message as Riya/), '   {Enter}')
    expect(onSend).not.toHaveBeenCalled()
  })
})

describe('MessageBubble', () => {
  const props = { people, onInspect: vi.fn(), onRetry: vi.fn() }
  it('shows a failure honestly, with the error and a retry', async () => {
    const onRetry = vi.fn()
    render(<MessageBubble {...props} onRetry={onRetry} message={message({ status: 'analysis_failed', error: 'Model unavailable: not loaded. Nothing was extracted.' })} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Analysis failed · Model unavailable')
    await userEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(onRetry).toHaveBeenCalledWith('A-1')
  })
  it('says a message was not analysed instead of implying a result', () => {
    render(<MessageBubble {...props} message={message({ status: 'no_extraction', error: 'No scripted extraction exists for this message.' })} />)
    expect(screen.getByText(/Not analysed/)).toBeInTheDocument()
    expect(screen.queryByText(/suggested/)).not.toBeInTheDocument()
  })
  it('summarises suggestions and no-change notes, and flags a mismatch with the scripted expectation', () => {
    render(<MessageBubble {...props} message={message({ pending_count: 2, applied_count: 1, no_change: ['owner acknowledges T-1'], matches_expectation: false, expected: { operations: ['CREATE_TASK'], note: 'x' } })} />)
    expect(screen.getByText('2 suggestions to review')).toBeInTheDocument()
    expect(screen.getByText('1 accepted')).toBeInTheDocument()
    expect(screen.getByText(/No change · owner acknowledges T-1/)).toBeInTheDocument()
    expect(screen.getByText('Differs from the scripted expectation')).toBeInTheDocument()
  })
  it('opens the inspector for the message', async () => {
    const onInspect = vi.fn()
    render(<MessageBubble {...props} onInspect={onInspect} message={message()} />)
    await userEvent.click(screen.getByRole('button', { name: /Inspect message from Riya/ }))
    expect(onInspect).toHaveBeenCalledWith('A-1')
  })
  it('has no accessibility violations', async () => expect(await axe(render(<MessageBubble {...props} message={message({ pending_count: 1 })} />).container)).toHaveNoViolations())
})

describe('SuggestionItem: review gating', () => {
  const h = { busy: false, onAccept: vi.fn(), onEdit: vi.fn(), onDismiss: vi.fn(), onSource: vi.fn() }
  it('accept works for a clear suggestion and shows the evidence', async () => {
    const onAccept = vi.fn()
    render(<ul><SuggestionItem {...h} onAccept={onAccept} s={suggestion()} /></ul>)
    expect(screen.getByText(/Anushree, please prepare the cleaned dataset by Thursday/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Accept' }))
    expect(onAccept).toHaveBeenCalled()
  })
  it('accept is disabled until the suggestion it depends on is accepted', () => {
    render(<ul><SuggestionItem {...h} s={suggestion({ kind: 'add_dependency', operation: 'ADD_DEPENDENCY', must_accept_first: [{ proposal_id: 'P-0', status: 'pending', summary: null }] })} /></ul>)
    expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled()
    expect(screen.getByText(/Waiting for another suggestion/)).toBeInTheDocument()
  })
  it('an unowned new task is never given a guessed owner: the viewer takes it or leaves it open', async () => {
    const onAccept = vi.fn()
    const s = suggestion({ unresolved: ['assignee'], reviewer_ids: [], after: { title: 'prepare the plan', owner_id: null, due: null }, flags: [{ code: 'NO_ASSIGNEE', severity: 'warn', field: 'assignee', message: 'm', question: 'Who should prepare it?' }] })
    render(<ul><SuggestionItem {...h} onAccept={onAccept} s={s} me="bianca" people={people} /></ul>)
    expect(screen.getByText('Who should prepare it?')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: "I'll take it" }))
    expect(onAccept).toHaveBeenLastCalledWith(s, { owner_id: 'bianca' })
    await userEvent.click(screen.getByRole('button', { name: 'Leave open' }))
    expect(onAccept).toHaveBeenLastCalledWith(s)
  })
  it('a reassignment with no clear new owner still needs Edit', () => {
    render(<ul><SuggestionItem {...h} s={suggestion({ operation: 'UPDATE_ASSIGNEE', kind: 'update_task', unresolved: ['assignee'], after: null })} me="riya" /></ul>)
    expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled()
  })
  it('an unresolved DUE date alone does not block accepting (it is stored as unresolved)', () => {
    render(<ul><SuggestionItem {...h} s={suggestion({ unresolved: ['due'] })} /></ul>)
    expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled()
  })
  it('an ambiguous referent needs a decision before accepting', () => {
    render(<ul><SuggestionItem {...h} s={suggestion({ kind: 'clarification', operation: 'COMPLETE_TASK', unresolved: ['task'], requires_referent: true })} /></ul>)
    expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeEnabled()
  })
  it('info-level flags stay out of the main list; acknowledgements read "Got it"', () => {
    render(<ul><SuggestionItem {...h} s={suggestion({ operation: 'NO_ACTION', kind: 'clarification', flags: [{ code: 'TENTATIVE_REQUEST', severity: 'info', field: 'request', message: 'Phrased as a question', question: 'Nothing needed.' }] })} /></ul>)
    expect(screen.queryByText('Nothing needed.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Got it' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })
  it('shows its provenance chip', () => {
    render(<ul><SuggestionItem {...h} s={suggestion({ source_kind: 'neural' })} /></ul>)
    expect(screen.getByText('neural')).toBeInTheDocument()
  })
})

describe('Review rights: the person a suggestion lands on decides it', () => {
  const h = { busy: false, onAccept: vi.fn(), onEdit: vi.fn(), onDismiss: vi.fn(), onSource: vi.fn() }
  it('speaks to the assignee in plain language', () => {
    render(<ul><SuggestionItem {...h} s={suggestion()} people={people} me="anushree" /></ul>)
    expect(screen.getByText('New task for you')).toBeInTheDocument()
    expect(screen.getByText('prepare the cleaned dataset')).toBeInTheDocument()
  })
  it('someone else sees who it is waiting for and cannot accept it', () => {
    render(<ul><SuggestionItem {...h} s={suggestion()} people={people} me="bianca" canDecide={false} canDismiss={false} waitingFor="Anushree" /></ul>)
    expect(screen.getByText('Waiting for Anushree to accept')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dismiss' })).not.toBeInTheDocument()
  })
  const panel = (me: string) => render(<TaskPanel tasks={[]} suggestions={[suggestion()]} people={people} active={people.find((p) => p.id === me)!} busy={false}
    onOpenTask={vi.fn()} onSource={vi.fn()} onAccept={vi.fn()} onEdit={vi.fn()} onDismiss={vi.fn()} onSwitchUser={vi.fn()} />)
  it('the project lead does NOT get a task assigned to Anushree in her queue', () => {
    panel('riya')
    expect(screen.queryByTestId('queue-count')).not.toBeInTheDocument()
    const waiting = screen.getByTestId('waiting-on-others')
    expect(within(waiting).getByText('Waiting for Anushree to accept')).toBeInTheDocument()
    expect(within(waiting).getByRole('button', { name: 'Dismiss' })).toBeInTheDocument()          // Riya wrote it, so she may withdraw a misread
    expect(within(waiting).getByRole('button', { name: 'Switch to Anushree' })).toBeInTheDocument()
  })
  it('the assignee sees it under "Needs you"', () => {
    panel('anushree')
    expect(screen.getByTestId('queue-count')).toHaveTextContent('1')
    expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled()
  })
  it('an unassigned task can be picked up by anyone', () => {
    render(<TaskPanel tasks={[]} suggestions={[suggestion({ reviewer_ids: [] })]} people={people} active={people[2]} busy={false}
      onOpenTask={vi.fn()} onSource={vi.fn()} onAccept={vi.fn()} onEdit={vi.fn()} onDismiss={vi.fn()} />)
    expect(screen.getByTestId('queue-count')).toHaveTextContent('1')
  })
})

describe('EditSuggestionDialog', () => {
  it('keeps the suggested owner when only the title is edited (it used to reset to unassigned)', async () => {
    const onSubmit = vi.fn()
    render(<EditSuggestionDialog suggestion={suggestion()} people={people} tasks={[]} onClose={vi.fn()} onSubmit={onSubmit} />)
    expect(screen.getByLabelText('Owner')).toHaveValue('anushree')
    await userEvent.clear(screen.getByLabelText('Title'))
    await userEvent.type(screen.getByLabelText('Title'), 'prepare the Q4 dataset')
    await userEvent.click(screen.getByRole('button', { name: 'Accept' }))
    expect(onSubmit).toHaveBeenCalledWith('P-1', { title: 'prepare the Q4 dataset' })
  })
})

describe('GraphTable (keyboard / screen-reader alternative)', () => {
  it('lists tasks and dependencies with direction and held reasons', () => {
    const g = graph(undefined, [edge(), edge({ id: 'E-2', source: 'T-2', target: 'T-1', kind: 'held', status: 'rejected', reason: 'CYCLE: closes a cycle' })])
    render(<GraphTable graph={g} people={people} onSelectEdge={vi.fn()} onSelectNode={vi.fn()} />)
    expect(screen.getByRole('table', { name: /Dependencies \(prerequisite → dependent\)/ })).toBeInTheDocument()
    expect(screen.getByText('held (cycle)')).toBeInTheDocument()
    expect(screen.getAllByText('train the entity model').length).toBeGreaterThan(0)
  })
  it('empty graph says so', () => {
    render(<GraphTable graph={graph([], [])} people={people} onSelectEdge={vi.fn()} onSelectNode={vi.fn()} />)
    expect(screen.getByText('No confirmed dependencies yet.')).toBeInTheDocument()
  })
  it('has no accessibility violations', async () => expect(await axe(render(<GraphTable graph={graph()} people={people} onSelectEdge={vi.fn()} onSelectNode={vi.fn()} />).container)).toHaveNoViolations())
})

describe('InspectorDrawer', () => {
  const open = (a = analysis()) => render(<InspectorDrawer open analysis={a} loading={false} people={people} onClose={vi.fn()} />)
  it('highlights the exact spans with their types', () => {
    open()
    const text = screen.getByTestId('highlighted-text')
    expect(within(text).getByText('Anushree', { selector: 'mark' })).toBeInTheDocument()
    expect(text.querySelectorAll('mark').length).toBe(3)
    expect(text).toHaveTextContent('TASK')
  })
  it('labels pre-written demo spans "scripted", never "neural"', () => {
    open()
    expect(screen.getAllByTestId('entity-row').map((r) => r.getAttribute('data-origin'))).toEqual(['scripted', 'scripted', 'scripted'])
  })
  it('says explicitly which classes the model cannot produce', async () => {
    open()
    expect(screen.getByText(/Not produced:/).parentElement).toHaveTextContent('GROUP, EVENT, ARTIFACT')
  })
  it('a failed analysis shows its error and no invented entities', () => {
    open(analysis({ entities: null, relations: [], error: 'Model unavailable: not loaded. Nothing was extracted.' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Nothing was extracted')
    expect(screen.getByText(/this message was not analysed/)).toBeInTheDocument()
  })
  it('shows relation provenance and calls scores uncalibrated', async () => {
    open(analysis({ relations: [{ source_id: 'e2', target_id: 'e1', label: 'ASSIGNED_TO', score: 0.9712, provenance: 'neural', model_version: 'relations-markers_sqrt', source_text: 'prepare it', target_text: 'Anushree' }] }))
    await userEvent.click(screen.getByRole('tab', { name: 'Links' }))
    const r = screen.getByTestId('relation')
    expect(r).toHaveTextContent('neural')
    expect(r).toHaveTextContent('0.971')
    expect(r).toHaveTextContent('uncalibrated')
  })
  it('a scripted relation says it has no model score', async () => {
    open()
    await userEvent.click(screen.getByRole('tab', { name: 'Links' }))
    expect(screen.getByTestId('relation')).toHaveTextContent('No model score')
    expect(screen.getByTestId('relation')).toHaveTextContent('scripted')
  })
  it('provenance tab separates every stage and shows the scripted expectation as NOT a prediction', async () => {
    open(analysis({ message: message({ expected: { operations: ['CREATE_TASK'], note: 'x' }, matches_expectation: true }), proposals: [{ ...suggestion() }] }))
    await userEvent.click(screen.getByRole('tab', { name: 'Sources' }))
    expect(screen.getByText('Entity extraction', { selector: 'td' }).closest('tr')).toHaveTextContent('scripted')
    expect(screen.getByText('Reconciliation', { selector: 'td' }).closest('tr')).toHaveTextContent('rule')
    expect(screen.getByText(/Scripted expectation \(not a model prediction\)/)).toBeInTheDocument()
    expect(screen.getByText(/not human-verified/)).toBeInTheDocument()
    expect(screen.getByText(/Attention weights and logits are not shown/)).toBeInTheDocument()
  })
  it('resolution shows raw → normalised and never a guessed value', async () => {
    const unresolved = { raw: 'next Friday', status: 'UNRESOLVED_NO_ANCHOR', granularity: null, start: null, end: null, value: null, assumptions: [], rule_id: 'weekday' }
    open(analysis({ candidates: [{ candidate_id: 'c1', title: 'prepare it', assignee: { participant_id: null, status: 'UNASSIGNED', basis: 'no_assignee_evidence' }, due: unresolved, scheduled: null, flags: [] }] }))
    await userEvent.click(screen.getByRole('tab', { name: 'People & dates' }))
    const panel = screen.getByRole('tabpanel')
    expect(within(panel).getAllByText(/“next Friday”/).length).toBeGreaterThan(0)
    expect(panel).toHaveTextContent('needs a reference time')
    expect(panel).not.toHaveTextContent(/\d{4}-\d{2}-\d{2}/)               // no date was invented
    expect(panel).toHaveTextContent('Owner: unresolved')
  })
})

describe('TaskDetails', () => {
  const props = { loading: false, people, activeId: 'riya', saving: false, onClose: vi.fn(), onInspect: vi.fn(), onOpenTask: vi.fn() }
  it('saves ONLY the changed fields with the expected version', async () => {
    const onSave = vi.fn()
    render(<TaskDetails {...props} onSave={onSave} task={taskDetail({ version: 3 })} />)
    await userEvent.clear(screen.getByLabelText('Title'))
    await userEvent.type(screen.getByLabelText('Title'), 'prepare the Q4 dataset')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(onSave).toHaveBeenCalledWith({ title: 'prepare the Q4 dataset' }, 3)
  })
  it('save is disabled until something changed', () => {
    render(<TaskDetails {...props} onSave={vi.fn()} task={taskDetail()} />)
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })
  it('a closed task cannot be moved to another status', () => {
    render(<TaskDetails {...props} onSave={vi.fn()} task={taskDetail({ lifecycle: 'completed', ui_status: 'done' })} />)
    expect(screen.getByLabelText('Status')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Mark done' })).not.toBeInTheDocument()
  })
  it('a pending date change is shown as NOT applied', () => {
    render(<TaskDetails {...props} onSave={vi.fn()} task={taskDetail({ pending_changes: { due: { value: resolved('2026-11-13', 'Friday'), proposer_id: 'riya', proposal_id: 'P-2', needs_confirmation_from: ['bianca'] } } })} />)
    expect(screen.getByText(/stays as shown until it is confirmed/)).toBeInTheDocument()
  })
  it('history shows provenance and the source quote opens the inspector', async () => {
    const onInspect = vi.fn()
    render(<TaskDetails {...props} onSave={vi.fn()} onInspect={onInspect} task={taskDetail()} />)
    expect(screen.getByRole('region', { name: 'History' })).toHaveTextContent('scripted')
    await userEvent.click(screen.getByRole('button', { name: /open in Inspector/ }))
    expect(onInspect).toHaveBeenCalledWith('A-1')
  })
  it('lists dependencies with direction', () => {
    render(<TaskDetails {...props} onSave={vi.fn()} task={taskDetail({ edges: [{ id: 'E-1', prerequisite: 'T-1', dependent: 'T-2', kind: 'accepted', evidence: '', source_message_id: 'A-3', source_kind: 'rule', reason: '' }] })} />)
    expect(screen.getByRole('region', { name: 'Dependencies' })).toHaveTextContent('Blocks')
  })
})

describe('WhatIfPanel calls the existing impact function and changes nothing', () => {
  it('shows who becomes ready', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ became_ready: ['T-2'], became_blocked: [], became_review: [], became_done: ['T-1'], became_cancelled: [], changed: {} }) })
    vi.stubGlobal('fetch', fetchMock)
    const Wrapper = () => {
      const [sel, setSel] = useState<string | null>(null)
      return <WhatIfPanel graph={graph()} task={graphNode({})} selected={sel} onSelect={setSel} />
    }
    render(<QueryClientProvider client={new QueryClient()}><Wrapper /></QueryClientProvider>)
    await userEvent.click(screen.getByRole('button', { name: /it were completed/ }))
    await waitFor(() => expect(screen.getByTestId('what-if-result')).toHaveTextContent('Becomes ready: train the entity model'))
    expect(fetchMock).toHaveBeenCalledWith('/api/impact?task_id=T-1&status=completed', expect.objectContaining({ method: 'GET' }))
    expect(fetchMock.mock.calls.every((c) => c[1].method === 'GET')).toBe(true)           // never a write
  })
})

describe('task fixture sanity', () => { it('builds', () => expect(task().id).toBe('T-1')) })
