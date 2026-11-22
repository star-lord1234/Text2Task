import { expect, test } from '@playwright/test'
import { acceptAll, loadScenario, next, shot } from './helpers'

test.use({ viewport: { width: 820, height: 900 } })
test('narrow window: no horizontal page scroll and the core controls stay reachable', async ({ page, request }) => {
  await request.post('/api/workspace/reset')
  await loadScenario(page, 'Scenario A — Simple assignment')
  await next(page, 1)
  await page.getByRole('tab', { name: 'Tasks' }).click()
  await acceptAll(page)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  await page.getByRole('radio', { name: 'Team' }).click()
  await expect(page.getByRole('region', { name: 'Tasks' })).toContainText('prepare the cleaned dataset')
  await page.getByRole('tab', { name: 'Chat' }).click()
  await expect(page.getByRole('button', { name: /^Next/ })).toBeVisible()
  await page.getByRole('link', { name: 'Dependencies' }).first().click()
  await expect(page.getByTestId('dependency-graph')).toBeVisible()
  await shot(page, '14-narrow-window')
})
