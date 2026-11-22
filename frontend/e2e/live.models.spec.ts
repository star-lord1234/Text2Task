import { expect, test } from '@playwright/test'
import { acceptAll, api, shot, switchUser } from './helpers'

// Runs against a server that loaded the REAL checkpoints. Assertions are about honesty and wiring, not about extraction accuracy:
// whatever the models return is what must be shown, mistakes included.
test.describe('Live mode with the real models', () => {
  test.beforeEach(async ({ request }) => { await request.post('/api/workspace/reset') })       // every test starts from an empty workspace

  test('capabilities report the real models and Live is enabled', async ({ page }) => {
    const cap = await api(page, '/api/system/capabilities')
    expect(cap.entity_model.available).toBe(true)
    expect(cap.relation_model.available).toBe(true)
    expect(cap.entity_model.provisional).toBe(true)
    expect(cap.modes.live).toBe(true)
    expect(cap.rule_fallback.enabled).toBe(false)
  })

  test('a live message shows the models\' actual output and neural provenance', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('t2t.mode', 'live'))
    await page.goto('/')
    await expect(page.getByTestId('mode-banner')).toContainText('Live AI')
    await expect(page.getByTestId('mode-banner')).toContainText('provisional')
    await page.getByRole('button', { name: 'Settings' }).first().click()
    await expect(page.getByRole('radio', { name: 'Live AI' })).toBeEnabled()
    await page.keyboard.press('Escape')
    await shot(page, '09-live-empty')

    await page.getByRole('button', { name: 'Message time' }).click()
    await page.getByLabel('Simulated message time').fill('2026-11-11T09:30')
    await page.getByLabel(/^Message as/).fill('Bianca, please prepare the report by Friday.')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByTestId(/^message-/)).toHaveCount(1)

    const ws = await api(page, '/api/workspace')
    const m = ws.messages[0]
    expect(m.mode).toBe('live')
    expect(m.status).toBe('analysed')
    expect(m.provenance.entities).toBe('neural')
    expect(m.provenance.relations).toBe('neural')

    // the Inspector shows exactly what the API recorded (including any model mistakes)
    const analysis = await api(page, `/api/messages/${m.id}/analysis`)
    await page.getByRole('button', { name: /^Inspect message/ }).click()
    const inspector = page.getByTestId('inspector')
    await expect(inspector).toBeVisible()
    for (const e of analysis.entities as Array<{ text: string }>) await expect(inspector.getByTestId('highlighted-text')).toContainText(e.text)
    await inspector.getByRole('tab', { name: 'Sources' }).click()
    await expect(inspector).toContainText('MailEx-derived SILVER labels, provisional, not human-verified')
    await expect(inspector).toContainText('neural')
    await expect(inspector).not.toContainText('Scripted expectation')
    await shot(page, '10-live-inspector-real-output')
  })

  test('live suggestions go through the same review step', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('t2t.mode', 'live'))
    await page.goto('/')
    await page.getByRole('button', { name: 'Message time' }).click()
    await page.getByLabel('Simulated message time').fill('2026-11-11T09:30')
    await page.getByLabel(/^Message as/).fill('Bianca, please prepare the report by Friday.')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByTestId(/^message-/)).toHaveCount(1)
    const before = await api(page, '/api/tasks')
    expect(before).toEqual([])                                  // review mode: nothing is applied automatically
    const queue = page.getByTestId(/^suggestion-/)
    if (await queue.count()) {
      await shot(page, '11-live-review-queue')
      await acceptAll(page)                                     // as the person each suggestion lands on
      await switchUser(page, 'Bianca')
    }
  })
})
