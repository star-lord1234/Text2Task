import { expect, test } from '@playwright/test'
import { acceptAll, api, loadScenario, next, shot, switchUser, taskRegion } from './helpers'

test.describe('Scenario A end to end (scripted extraction, real reconciliation)', () => {
  test.beforeEach(async ({ request }) => { await request.post('/api/workspace/reset') })       // every test starts from an empty workspace

  test('demo journey: assign, switch users, dependency, completion unblocks, inspector', async ({ page }) => {
    await loadScenario(page, 'Scenario A — Simple assignment')
    await expect(page.getByTestId('mode-banner')).toContainText('Demo story')
    await shot(page, '01-workspace-empty')

    // 1. Riya assigns Anushree: a SUGGESTION appears, nothing is a task yet
    await next(page, 1)
    await expect(page.getByTestId(/^suggestion-/)).toHaveCount(1)
    await expect(page.getByTestId(/^suggestion-/)).toContainText('prepare the cleaned dataset')
    expect(await api(page, '/api/tasks')).toEqual([])
    await shot(page, '02-suggestion-in-review-queue')
    await acceptAll(page)

    // 2. persona switch: the task is in Anushree's list and not in Bianca's
    await switchUser(page, 'Anushree')
    await expect(taskRegion(page).getByText('prepare the cleaned dataset')).toBeVisible()
    await shot(page, '03-anushree-my-tasks')
    await switchUser(page, 'Bianca')
    await expect(taskRegion(page).getByText("Nothing on Bianca's plate")).toBeVisible()

    // 3. acknowledgement creates NO duplicate
    await next(page, 2)
    await expect(page.getByText(/No change · owner acknowledges/)).toBeVisible()
    expect((await api(page, '/api/tasks')).length).toBe(1)

    // 4. dependent task + prerequisite edge: the edge can only be accepted after its task
    await next(page, 3)
    const edgeAccept = page.getByTestId(/^suggestion-/).filter({ hasText: 'Has to wait' }).getByRole('button', { name: 'Accept', exact: true })
    await expect(edgeAccept).toBeDisabled()
    await acceptAll(page)
    await switchUser(page, 'Bianca')
    await expect(taskRegion(page).getByText('train the entity model').first()).toBeVisible()
    await expect(taskRegion(page).getByText('Blocked').first()).toBeVisible()

    // 5. graph: prerequisite -> dependent, blocked label (icon + text)
    await page.getByRole('link', { name: 'Dependencies' }).first().click()
    await expect(page.getByTestId('dependency-graph')).toBeVisible()
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await expect(page.getByTestId('node-T-2')).toHaveAttribute('data-state', 'blocked')
    await expect(page.getByTestId('node-T-2')).toContainText('Blocked')
    await page.locator('.react-flow__edge').first().click({ force: true })
    await expect(page.getByTestId('edge-details')).toContainText('prepare the cleaned dataset')
    await shot(page, '04-dependency-explorer-blocked')

    // 6. completion unblocks the dependent task
    await page.getByRole('link', { name: 'team-chat' }).first().click()
    await next(page, 4)
    await acceptAll(page)
    await page.getByRole('link', { name: 'Dependencies' }).first().click()
    await expect(page.getByTestId('node-T-2')).toHaveAttribute('data-state', 'ready')
    await shot(page, '05-dependency-explorer-unblocked')

    // 7. progress update on the EXISTING task, still no duplicate
    await page.getByRole('link', { name: 'team-chat' }).first().click()
    await next(page, 5)
    await acceptAll(page)
    const tasks = await api(page, '/api/tasks')
    expect(tasks.map((t: any) => [t.id, t.ui_status])).toEqual([['T-1', 'done'], ['T-2', 'in_progress']])

    // 8. the Inspector shows scripted provenance and the scripted expectation
    await page.getByRole('button', { name: /^Inspect message from Riya/ }).nth(1).click()
    const inspector = page.getByTestId('inspector')
    await expect(inspector).toBeVisible()
    const text = inspector.getByTestId('highlighted-text')
    await expect(text).toContainText('please train the entity model')
    await expect(text.locator('mark')).toHaveCount(3)           // Bianca, 'train the entity model', Anushree
    await inspector.getByRole('tab', { name: 'Links' }).click()
    await expect(inspector.getByTestId('relation').first()).toContainText('scripted')
    await inspector.getByRole('tab', { name: 'Sources' }).click()
    await expect(inspector.getByRole('tab', { name: 'Sources' })).toHaveAttribute('aria-selected', 'true')
    await expect(inspector.getByRole('tab', { name: 'Links' })).toHaveAttribute('aria-selected', 'false')
    await expect(inspector).toContainText('Scripted expectation (not a model prediction)')
    await expect(inspector).toContainText('✓ matches')
    await shot(page, '06-ai-inspector-provenance')
  })

  test('switching persona writes nothing', async ({ page }) => {
    await loadScenario(page, 'Scenario A — Simple assignment')
    await next(page, 1); await acceptAll(page); await next(page, 2)
    const before = JSON.stringify([await api(page, '/api/tasks'), (await api(page, '/api/workspace')).messages.length])
    for (const who of ['Anushree', 'Bianca', 'Riya']) await switchUser(page, who)
    expect(JSON.stringify([await api(page, '/api/tasks'), (await api(page, '/api/workspace')).messages.length])).toBe(before)
  })

  test('previous step and reset restore the exact state', async ({ page }) => {
    await loadScenario(page, 'Scenario A — Simple assignment')
    await next(page, 1); await acceptAll(page); await next(page, 2); await next(page, 3); await acceptAll(page)
    const atThree = JSON.stringify(await api(page, '/api/tasks'))
    await next(page, 4); await acceptAll(page)
    await page.getByRole('button', { name: 'Previous' }).click()
    await expect(page.getByTestId('scenario-step')).toContainText('Step 3 of')
    expect(JSON.stringify(await api(page, '/api/tasks'))).toBe(atThree)
    await page.getByRole('button', { name: 'Reset scenario' }).click()
    await expect(page.getByTestId('scenario-step')).toContainText('Step 0 of')
    expect(await api(page, '/api/tasks')).toEqual([])
    await expect(page.getByText('No messages yet')).toBeVisible()
  })

  test('Scenario B: a proposed deadline change does not apply until it is confirmed', async ({ page }) => {
    await loadScenario(page, 'Scenario B — Deadline change')
    await next(page, 1); await acceptAll(page)
    await next(page, 2); await acceptAll(page)
    let task = await api(page, '/api/tasks/T-1')
    expect(task.due.value).toBe('2026-11-12')
    await switchUser(page, 'Bianca')                            // the task is Bianca's, so it is in HER list, not Riya's
    await expect(page.getByText(/New date Fri 13 Nov awaiting OK/)).toBeVisible()
    await shot(page, '07-deadline-proposal-pending')
    await next(page, 3); await acceptAll(page)
    task = await api(page, '/api/tasks/T-1')
    expect(task.due.value).toBe('2026-11-13')
    expect(task.history.map((h: any) => h.operation)).toContain('PROPOSE_DUE_DATE_CHANGE')
  })

  test('Live mode is unavailable and says so; typing is disabled; nothing is invented', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('t2t.mode', 'live'))
    await page.goto('/')
    await expect(page.getByTestId('mode-banner')).toContainText('Model unavailable')
    await page.getByRole('button', { name: 'Settings' }).first().click()
    await expect(page.getByRole('radio', { name: 'Live AI' })).toBeDisabled()
    await page.keyboard.press('Escape')
    await expect(page.getByLabel(/^Message as/)).toBeDisabled()
    await expect(page.getByPlaceholder(/Model unavailable: Live analysis cannot run/)).toBeVisible()
    expect((await api(page, '/api/workspace')).tasks).toEqual([])
    await shot(page, '08-live-model-unavailable')
  })

  test('selected toggles and primary buttons are legible (regression: unlayered CSS once beat Tailwind utilities)', async ({ page }) => {
    await loadScenario(page, 'Scenario A — Simple assignment')
    await next(page, 1)
    await switchUser(page, 'Anushree')                          // the new task is hers, so she is the one who sees Accept
    // resolve ANY css colour (rgb, oklab, color-mix...) to sRGB by painting it on a canvas, then take its WCAG luminance
    const luminance = (loc: import('@playwright/test').Locator, prop: string) => loc.evaluate((el, p) => {
      const ctx = document.createElement('canvas').getContext('2d')!
      ctx.fillStyle = getComputedStyle(el).getPropertyValue(p); ctx.fillRect(0, 0, 1, 1)
      const lin = (c: number) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }
      const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data
      return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    }, prop)
    for (const loc of [page.getByRole('radio', { name: 'Mine' }), page.getByRole('button', { name: 'Accept', exact: true }), page.getByRole('button', { name: /^Next/ })]) {
      const [fg, bg] = [await luminance(loc, 'color'), await luminance(loc, 'background-color')]
      expect((Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05)).toBeGreaterThan(4.5)   // WCAG AA contrast for the label on its own background
    }
  })

  test('keyboard: the review queue can be operated without a mouse', async ({ page }) => {
    await loadScenario(page, 'Scenario A — Simple assignment')
    await next(page, 1)
    await switchUser(page, 'Anushree')
    const accept = page.getByTestId(/^suggestion-/).getByRole('button', { name: 'Accept', exact: true })
    await accept.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByTestId(/^suggestion-/)).toHaveCount(0)
    expect((await api(page, '/api/tasks')).length).toBe(1)
  })
})
