import { expect, test, type Page } from '@playwright/test'
import { api, shot } from './helpers'

// Real checkpoints. Assertions tie the screen to what the API recorded (raw neural vs refined vs rule) and check the behaviours Phase 7.5 added;
// they do not assert general model accuracy.
const TS = '2026-11-11T09:30:00-06:00'
const post = async (page: Page, sender: string, rec: string[], text: string, at = TS) =>
  (await page.request.post('/api/messages', { data: { sender_id: sender, recipient_ids: rec, text, mode: 'live', created_at: at } })).json()
const preset = (page: Page, name: string) => page.request.put('/api/settings', { data: { pipeline_preset: name, refine_overrides: {}, timezone: 'America/Chicago' } })

test.describe('Hybrid pipeline with the real models', () => {
  test.beforeEach(async ({ request }) => { await request.post('/api/workspace/reset') })

  test('the Inspector shows raw neural spans, refined spans and their origin, matching the API record', async ({ page }) => {
    await preset(page, 'hybrid')
    await page.addInitScript(() => localStorage.setItem('t2t.mode', 'live'))
    await page.goto('/')
    await page.getByRole('button', { name: 'Settings' }).first().click()
    await expect(page.getByLabel('Pipeline')).toHaveValue('hybrid')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Message time' }).click()
    await page.getByLabel('Simulated message time').fill('2026-11-11T09:30')
    await page.getByLabel(/^Message as/).fill('Bianca, please prepare the report by Friday.')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByTestId(/^message-/)).toHaveCount(1)
    const m = (await api(page, '/api/workspace')).messages[0]
    const rec = (await api(page, `/api/messages/${m.id}/analysis`)).refinement
    expect(rec.config.preset).toBe('hybrid')
    expect(rec.raw_entities.length).toBeGreaterThan(0)

    await page.getByRole('button', { name: /^Inspect message/ }).click()
    const inspector = page.getByTestId('inspector')
    const rows = inspector.getByTestId('entity-row')
    await expect(rows).toHaveCount(rec.entities.length)
    expect(await rows.evaluateAll((r) => r.map((x) => x.getAttribute('data-origin')))).toEqual(rec.entities.map((e: { origin: string }) => e.origin))
    // every span that is not plain neural says what was done to it
    for (let i = 0; i < rec.entities.length; i++) {
      if (rec.entities[i].origin === 'neural') continue
      const cell = (await rows.nth(i).locator('td').nth(1).innerText()).trim()
      expect(cell.split('\n').length).toBeGreaterThan(1)               // span text plus at least one line saying what was done and by which rule
      expect(rec.entities[i].refinement.length).toBeGreaterThan(0)
    }
    await shot(page, '18-inspector-refined-spans')
    // the raw neural spans are one click away and are exactly what the model returned
    await inspector.getByRole('radio', { name: 'Raw neural' }).click()
    const marks = await inspector.getByTestId('highlighted-text').locator('mark').evaluateAll((ms) => ms.map((x) => (x.textContent ?? '').split(' (')[0]))
    expect(marks).toEqual(rec.raw_entities.map((e: { text: string }) => e.text))
    await shot(page, '19-inspector-raw-neural-spans')
    await inspector.getByRole('tab', { name: 'Sources' }).click()
    await expect(inspector.getByTestId('refine-config')).toBeVisible()
    await expect(inspector).toContainText('Span refinement')
  })

  test('switching the pipeline to neural only removes every refinement, and says so', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('t2t.mode', 'live'))
    await page.goto('/')
    await page.getByRole('button', { name: 'Settings' }).first().click()
    await page.getByLabel('Pipeline').selectOption('neural_only')
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('mode-banner')).toContainText('neural only')
    await page.getByRole('button', { name: 'Message time' }).click()
    await page.getByLabel('Simulated message time').fill('2026-11-11T09:30')
    await page.getByLabel(/^Message as/).fill('Bianca, please prepare the report by Friday.')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByTestId(/^message-/)).toHaveCount(1)
    await page.getByRole('button', { name: /^Inspect message/ }).click()
    const inspector = page.getByTestId('inspector')
    expect(await inspector.getByTestId('entity-row').evaluateAll((r) => r.map((x) => x.getAttribute('data-origin')))).not.toContain('refined')
    await expect(inspector.getByRole('radio', { name: 'Raw neural' })).toHaveCount(0)
  })

  test('a dependency written in one sentence is recovered by hybrid and missed by neural only; review mode still applies', async ({ page }) => {
    const text = 'After you clean the dataset, write a report.'
    await preset(page, 'neural_only')
    const base = await post(page, 'riya', ['anushree', 'bianca'], text)
    expect(base.proposals.filter((p: { operation: string }) => p.operation !== 'NO_ACTION')).toEqual([])
    await page.request.post('/api/workspace/reset')
    await preset(page, 'hybrid')
    const a = await post(page, 'riya', ['anushree', 'bianca'], text)
    expect(a.proposals.map((p: { operation: string }) => p.operation).sort()).toEqual(['ADD_DEPENDENCY', 'CREATE_TASK', 'CREATE_TASK'])
    expect(await api(page, '/api/tasks')).toEqual([])                              // nothing applied yet
    const rule = a.relations.find((r: { label: string }) => r.label === 'DEPENDS_ON')
    expect(rule.provenance).toBe('rule')

    await page.addInitScript(() => localStorage.setItem('t2t.mode', 'live'))
    await page.goto('/')
    for (const op of ['CREATE_TASK', 'CREATE_TASK']) {
      const s = (await api(page, '/api/suggestions')).find((x: { operation: string }) => x.operation === op)
      expect((await page.request.post(`/api/suggestions/${s.id}/accept`, { data: { actor_id: 'riya', edits: { owner_id: null } } })).ok()).toBeTruthy()
    }
    const dep = (await api(page, '/api/suggestions')).find((x: { operation: string }) => x.operation === 'ADD_DEPENDENCY')
    expect((await page.request.post(`/api/suggestions/${dep.id}/accept`, { data: { actor_id: 'riya' } })).ok()).toBeTruthy()
    await page.getByRole('link', { name: 'Dependencies' }).first().click()
    await expect(page.getByTestId('dependency-graph')).toBeVisible()
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await shot(page, '20-live-clause-dependency-graph')
    await page.goto('/')
    await page.getByRole('button', { name: /^Inspect message/ }).click()
    await page.getByTestId('inspector').getByRole('tab', { name: 'Links' }).click()
    await expect(page.getByTestId('inspector').getByText('Generated by rules')).toBeVisible()
    await expect(page.getByTestId('inspector')).toContainText('rule: clause:cue_first')
    await shot(page, '21-inspector-rule-dependency')
  })

  test('a completion report with no task phrase still completes the existing task (after review)', async ({ page }) => {
    await preset(page, 'hybrid')
    await post(page, 'riya', ['anushree'], 'Anushree, please clean the dataset by Thursday.')
    const s = (await api(page, '/api/suggestions')).find((x: { operation: string }) => x.operation === 'CREATE_TASK')
    await page.request.post(`/api/suggestions/${s.id}/accept`, { data: { actor_id: 'anushree' } })   // the assignee accepts her own task
    const b = await post(page, 'anushree', ['riya'], 'The dataset is cleaned.', '2026-11-11T09:50:00-06:00')
    expect(b.entities).toEqual([])                                                 // the model found no TASK span at all
    expect(b.proposals.map((p: { operation: string }) => p.operation)).toEqual(['COMPLETE_TASK'])
    expect((await api(page, '/api/tasks'))[0].lifecycle).toBe('open')              // still a suggestion
    await preset(page, 'neural_only')
    const c = await post(page, 'anushree', ['riya'], 'The dataset is cleaned. ', '2026-11-11T09:51:00-06:00')
    expect(c.proposals.filter((p: { operation: string }) => p.operation !== 'NO_ACTION')).toEqual([])
  })
})
