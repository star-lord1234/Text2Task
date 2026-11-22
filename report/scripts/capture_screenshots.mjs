// Capture the report's application screenshots from a REAL running Text2Task server (real models for Live mode).
// Start the server first (see report/README.md), then:  node report/scripts/capture_screenshots.mjs http://127.0.0.1:8799
// Playwright is resolved from the frontend's node_modules; nothing here is mocked.
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.resolve(here, '../../frontend/package.json'))
const { chromium } = require('@playwright/test')
const base = process.argv[2] ?? 'http://127.0.0.1:8799'
const OUT = path.resolve(here, '../figures/screenshots')

const b = await chromium.launch()
const ctx = await b.newContext({ viewport: { width: 1440, height: 860 }, deviceScaleFactor: 2, reducedMotion: 'reduce' })
const page = await ctx.newPage()
const api = async (method, url, data) => {
  const r = await page.request.fetch(base + url, { method, data })
  if (!r.ok()) throw new Error(`${method} ${url} -> ${r.status()} ${await r.text()}`)
  return r.json()
}
const shot = async (name, opts = {}) => { await page.waitForTimeout(500); await page.screenshot({ path: `${OUT}/${name}.png`, ...opts }); console.log('shot', name) }
const as = async (user, mode = 'scripted', route = '/') => {
  await page.goto(base + route)
  await page.evaluate(([u, m]) => { localStorage.setItem('t2t.user', u); localStorage.setItem('t2t.mode', m) }, [user, mode])
  await page.goto(base + route); await page.waitForTimeout(900)
}
const reviewer = (s) => (s.reviewer_ids.length ? s.reviewer_ids[0] : 'riya')
async function acceptAll() {
  for (let pass = 0; pass < 2; pass++) {
    for (const s of await api('GET', '/api/suggestions')) {
      if (s.operation === 'NO_ACTION' || s.requires_referent) continue
      if (s.unresolved.some((u) => !(u === 'assignee' && s.operation === 'CREATE_TASK'))) continue
      await page.request.post(`${base}/api/suggestions/${s.id}/accept`, { data: { actor_id: reviewer(s) } })
    }
  }
}
const step = async (n, accept = true) => { for (let i = 0; i < n; i++) { await api('POST', '/api/scenarios/step'); if (accept) await acceptAll() } }
const live = (sender, to, text, minute) => api('POST', '/api/messages', { sender_id: sender, recipient_ids: to, text, mode: 'live', created_at: `2026-11-11T10:${String(minute).padStart(2, '0')}:00-06:00` })

// ---- 1. Scenario F mid-way: Bianca's view with work waiting for her --------------------------------------------------
await api('POST', '/api/workspace/reset')
await api('POST', '/api/scenarios/F/load')
await step(9); await step(1, false)                       // message 10 arrives, not yet reviewed
await as('bianca'); await shot('01_workspace_needs_you')

// ---- 2. Date-change request then confirmation (task modification proposal) ------------------------------------------
await acceptAll(); await step(2); await step(1, false)    // messages 11-12 reviewed, 13 ("Friday is fine.") arrives
await as('riya')
await page.getByRole('radio', { name: 'Team' }).click()
await shot('02_date_change_confirmation')

// ---- 3. Finish the story: dependency graph, timeline, task details ----------------------------------------------------
await acceptAll(); await step(4)
await as('riya', 'scripted', '/dependencies'); await page.getByRole('button', { name: 'Fit', exact: true }).click()
await page.getByTestId('node-T-7').click(); await shot('03_dependency_graph')
await as('riya', 'scripted', '/timeline'); await shot('04_timeline', { clip: { x: 0, y: 0, width: 1440, height: 420 } })

// ---- 4. Scenario C: ambiguous volunteer -> referent chooser ------------------------------------------------------------
await api('POST', '/api/workspace/reset'); await api('POST', '/api/scenarios/C/load')
for (let i = 0; i < 2; i++) {
  await api('POST', '/api/scenarios/step')
  const [s] = await api('GET', '/api/suggestions')
  await page.request.post(`${base}/api/suggestions/${s.id}/accept`, { data: { actor_id: 'riya' } })      // left open (no owner invented)
}
await api('POST', '/api/scenarios/step')
await as('anushree')
await page.getByTestId(/^suggestion-/).getByRole('button', { name: 'Edit' }).click()
await shot('05_ambiguous_referent')
await page.keyboard.press('Escape')

// ---- 5. Live mode with the real models -----------------------------------------------------------------------------------
await api('POST', '/api/workspace/reset')
await api('PUT', '/api/settings', { pipeline_preset: 'hybrid', refine_overrides: {} })
await as('riya', 'live')
await page.getByRole('button', { name: 'Message time' }).click()
await page.getByLabel('Simulated message time').fill('2026-11-11T10:00')
await page.getByLabel(/^Message as/).fill('Bianca please prepare the quarterly report by Friday.')
await page.getByRole('button', { name: 'Send' }).click()
await page.waitForTimeout(2500)
await live('riya', ['anushree', 'bianca'], 'Please book the demo meeting for next Tuesday.', 2)
await live('anushree', ['riya', 'bianca'], 'The server went down yesterday.', 3)
await live('bianca', ['riya'], 'Thanks, that sounds good!', 4)
await as('bianca', 'live'); await shot('06_live_extraction')

const msgs = (await api('GET', '/api/workspace')).messages
await page.getByRole('button', { name: /^Inspect message from Riya/ }).first().click({ force: true })
await shot('07_inspector_hybrid')
await page.getByRole('radio', { name: 'Raw neural' }).click()
await shot('08_inspector_raw_neural')
await page.getByRole('tab', { name: 'Sources' }).click()
await shot('09_inspector_sources')
await page.keyboard.press('Escape')

// ---- 6. A documented failure case (Phase 7.5 report, false positive) ------------------------------------------------------
await api('POST', '/api/workspace/reset')
await live('riya', ['bianca'], 'Bianca, call me after the meeting.', 10)
await live('riya', ['anushree'], 'Deployment can\'t start until the test server is set up.', 11)
await as('bianca', 'live')
await page.getByRole('button', { name: /^Inspect message from Riya/ }).first().click({ force: true })
await shot('10_failure_case')
await page.keyboard.press('Escape')

console.log(JSON.stringify(msgs.map((m) => ({ id: m.id, text: m.text, status: m.status, proposals: m.proposals.map((p) => p.summary) })), null, 1))
await b.close()
