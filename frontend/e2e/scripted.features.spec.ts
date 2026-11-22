import { expect, test } from '@playwright/test'
import { acceptAll, api, loadScenario, next, shot } from './helpers'

test.describe('Optional views and Scenarios C/E (scripted extraction, real reconciliation)', () => {
  test.beforeEach(async ({ request }) => { await request.post('/api/workspace/reset') })

  test('what-if: previewing completion changes nothing but shows the effect', async ({ page }) => {
    await loadScenario(page, 'Scenario A — Simple assignment')
    for (let i = 1; i <= 3; i++) { await next(page, i); await acceptAll(page) }
    await page.getByRole('link', { name: 'Dependencies' }).first().click()
    await page.getByTestId('node-T-1').click()
    const panel = page.getByTestId('what-if')
    await panel.getByRole('button', { name: /completed/ }).click()
    await expect(page.getByTestId('what-if-result')).toContainText('Becomes ready')
    await expect(page.getByTestId('what-if-result')).toContainText('train the entity model')
    expect((await api(page, '/api/tasks')).map((t: { lifecycle: string }) => t.lifecycle)).toEqual(['open', 'open'])   // nothing was changed
    await expect(page.getByTestId('node-T-2')).toHaveAttribute('data-state', 'blocked')
    await shot(page, '15-what-if-preview')
  })

  test('timeline: confirmed deadlines are placed; tasks without a confirmed date are listed, not placed', async ({ page }) => {
    await loadScenario(page, 'Scenario A — Simple assignment')
    for (let i = 1; i <= 3; i++) { await next(page, i); await acceptAll(page) }
    await page.getByRole('link', { name: 'Timeline' }).click()
    await expect(page.getByRole('button', { name: /prepare the cleaned dataset/ })).toHaveAttribute('title', /Due Thu 12 Nov/)
    await expect(page.getByRole('columnheader', { name: 'No date yet' })).toBeVisible()
    await expect(page.getByRole('button', { name: /train the entity model/ })).toHaveAttribute('title', /No confirmed date/)   // listed, never placed on a guessed day
    await shot(page, '16-deadline-timeline')
    await page.getByRole('button', { name: /prepare the cleaned dataset/ }).click()
    await expect(page.getByRole('dialog')).toContainText('prepare the cleaned dataset')
  })

  test('evaluation dashboard shows the saved results, the SILVER statement and the limitations', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: 'Model results' }).first().click()
    await expect(page.getByText(/No human-verified GOLD evaluation exists/)).toBeVisible()
    const saved = await api(page, '/api/evaluation')
    await expect(page.getByText(saved.relations.mode_a.neural.micro_f1.toFixed(3), { exact: false }).first()).toBeVisible()
    await expect(page.getByText(/DUE_ON is weak and unstable/)).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Entity extraction' })).toBeVisible()
    await shot(page, '17-evaluation-dashboard')
  })

  test('Scenario C: ambiguous volunteer shows the options; nothing changes until a person chooses', async ({ page }) => {
    await loadScenario(page, 'Scenario C — Ambiguity')
    for (const i of [1, 2]) {
      await next(page, i)
      const card = page.getByTestId(/^suggestion-/)
      await expect(card).toContainText(/Who should review the slides/)   // the UI never offers a plain Accept that would invent an owner...
      await expect(card.getByRole('button', { name: 'Accept', exact: true })).toHaveCount(0)
      await card.getByRole('button', { name: 'Leave open' }).click()     // ...it adds the task without one, for a volunteer to claim
      await expect(page.getByTestId(/^suggestion-/)).toHaveCount(0)
    }
    expect((await api(page, '/api/tasks')).map((t: { owner_id: string | null }) => t.owner_id)).toEqual([null, null])   // nobody named: no owner invented
    await next(page, 3)
    const card = page.getByTestId(/^suggestion-/)
    await expect(card).toHaveCount(1)
    await expect(card).toContainText(/Which task/i)
    const sw = card.getByRole('button', { name: /^Switch to / })
    if (await sw.count()) await sw.click()                     // only the person it lands on sees Accept
    await expect(card.getByRole('button', { name: 'Accept', exact: true })).toBeDisabled()            // cannot be accepted until a person chooses
    expect((await api(page, '/api/tasks')).map((t: { owner_id: string | null }) => t.owner_id)).toEqual([null, null])   // nothing was guessed
    await shot(page, '12-ambiguous-referent')
  })

  test('Scenario E: the reverse dependency is held for review and the graph stays valid', async ({ page }) => {
    await loadScenario(page, 'Scenario E — Dependency conflict')
    for (let i = 1; i <= 4; i++) { await next(page, i); await acceptAll(page) }
    const g = await api(page, '/api/dependencies')
    expect(g.meta.acyclic).toBe(true)
    expect(g.edges.map((e: { kind: string }) => e.kind).sort()).toEqual(['accepted', 'held'])
    await page.getByRole('link', { name: 'Dependencies' }).first().click()
    await expect(page.locator('.react-flow__edge')).toHaveCount(2)          // the held edge is drawn (dotted, labelled), never dropped
    await expect(page.getByText('held: cycle')).toBeVisible()
    await expect(page.getByTestId('node-T-2')).toHaveAttribute('data-state', 'blocked')   // blocked only by the accepted edge
    await shot(page, '13-held-cycle-edge')
  })
})
