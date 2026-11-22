import { defineConfig } from '@playwright/test'

const PY = '.venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1'

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: [['list']],
  use: { viewport: { width: 1440, height: 900 }, contextOptions: { reducedMotion: 'reduce' }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [
    { name: 'scripted', testMatch: /scripted\..*\.spec\.ts/, use: { baseURL: 'http://127.0.0.1:8766' } },
    { name: 'live', testMatch: /live\..*\.spec\.ts/, use: { baseURL: 'http://127.0.0.1:8767' } },
  ],
  webServer: [
    // scripted-only server: models disabled, so Live mode must report "model unavailable"
    { command: `cd .. && T2T_DB=:memory: T2T_NO_MODELS=1 ${PY} --port 8766`, url: 'http://127.0.0.1:8766/api/system/health', reuseExistingServer: false, timeout: 60_000 },
    // live server: the real checkpoints are loaded once at startup
    { command: `cd .. && T2T_DB=:memory: ${PY} --port 8767`, url: 'http://127.0.0.1:8767/api/system/health', reuseExistingServer: false, timeout: 180_000 },
  ],
})
