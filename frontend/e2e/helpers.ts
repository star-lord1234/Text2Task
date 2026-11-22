import { expect, type Page } from '@playwright/test'
import path from 'node:path'

export const SHOTS = path.resolve(process.cwd(), '../results/phase7/screenshots')
export const shot = (page: Page, name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) })

export async function loadScenario(page: Page, title: RegExp | string) {
  await page.goto('/')
  const short = String(title).replace(/^Scenario \w+ — /, '')
  await page.getByRole('button', { name: 'Settings' }).first().click()
  await page.getByRole('radio', { name: new RegExp(short.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click()
  await expect(page.getByTestId('scenario-step')).toContainText('Step 0 of')
}

export const next = async (page: Page, step: number) => {
  await page.getByRole('button', { name: /^Next/ }).click()
  await expect(page.getByTestId('scenario-step')).toContainText(`Step ${step} of`)
}

/** Accept every suggestion as the person it lands on: only they see an Accept button, so switch to them when needed. */
export async function acceptAll(page: Page) {
  for (let guard = 0; guard < 12; guard++) {
    const accept = page.getByTestId(/^suggestion-/).getByRole('button', { name: 'Accept', exact: true })
    const enabled = accept.and(page.locator(':enabled')).first()
    if (await enabled.count()) {
      const before = await page.getByTestId(/^suggestion-/).count()
      await enabled.click()
      await expect(page.getByTestId(/^suggestion-/)).toHaveCount(before - 1)
      continue
    }
    const sw = page.getByRole('button', { name: /^Switch to / }).first()
    if (!(await sw.count())) break
    const name = (await sw.textContent())!.replace('Switch to ', '').trim()
    await sw.click()
    await expect(page.getByRole('button', { name: new RegExp(`^Viewing as ${name}`) }).first()).toBeAttached()
    if (!(await accept.and(page.locator(':enabled')).count())) break                          // its Accept is still gated (e.g. needs its task first)
  }
}

export async function switchUser(page: Page, name: string) {
  await page.getByRole('button', { name: /^Viewing as / }).first().click()
  await page.getByRole('menuitemradio', { name: new RegExp(`^${name}`) }).click()
  await expect(page.getByRole('button', { name: new RegExp(`^Viewing as ${name}\\.`) }).first()).toBeAttached()
}

export const taskRegion = (page: Page) => page.getByRole('region', { name: 'Tasks' })
export const api = async (page: Page, url: string) => (await page.request.get(url)).json()
