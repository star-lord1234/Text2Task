import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { people } from '../test/fixtures'
import { UIProvider, useActiveUser, useUI } from './ui'

function Probe() {
  const active = useActiveUser(people)
  const ui = useUI()
  return (
    <div>
      <span data-testid="who">{active?.name}</span><span data-testid="mode">{ui.mode}</span>
      {people.map((p) => <button key={p.id} onClick={() => ui.setActiveUserId(p.id)}>as {p.name}</button>)}
      <button onClick={() => ui.setMode('live')}>live</button>
    </div>
  )
}

afterEach(() => { vi.restoreAllMocks(); localStorage.clear() })

describe('persona and mode are client state only', () => {
  it('switching persona never calls the API', async () => {
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock)
    render(<UIProvider><Probe /></UIProvider>)
    expect(screen.getByTestId('who')).toHaveTextContent('Riya')
    await userEvent.click(screen.getByRole('button', { name: 'as Bianca' }))
    expect(screen.getByTestId('who')).toHaveTextContent('Bianca')
    await userEvent.click(screen.getByRole('button', { name: 'as Anushree' }))
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it('remembers the persona and the mode across reloads', async () => {
    const first = render(<UIProvider><Probe /></UIProvider>)
    await userEvent.click(screen.getByRole('button', { name: 'as Anushree' }))
    await userEvent.click(screen.getByRole('button', { name: 'live' }))
    first.unmount()
    render(<UIProvider><Probe /></UIProvider>)
    expect(screen.getByTestId('who')).toHaveTextContent('Anushree')
    expect(screen.getByTestId('mode')).toHaveTextContent('live')
  })
  it('defaults to scripted mode', () => {
    render(<UIProvider><Probe /></UIProvider>)
    expect(screen.getByTestId('mode')).toHaveTextContent('scripted')
  })
})
