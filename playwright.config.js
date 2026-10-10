// Playwright recipes against a synthetic, deterministic workspace (see e2e/fixtures/build.py).
import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT || 8799);
const CI = !!process.env.CI;
// Set to test a deployed build (e.g. a Vercel preview) instead of the local fixture workspace.
const REMOTE = process.env.E2E_BASE_URL;
const BYPASS = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;

export default defineConfig({
  testDir: 'e2e/recipes',
  outputDir: 'e2e/.results',
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  workers: CI ? 2 : undefined,
  reporter: CI
    ? [['github'], ['html', { outputFolder: 'e2e/.report', open: 'never' }], ['junit', { outputFile: 'e2e/.results/junit.xml' }]]
    : [['list'], ['html', { outputFolder: 'e2e/.report', open: 'never' }]],
  use: {
    baseURL: REMOTE || `http://127.0.0.1:${PORT}`,
    extraHTTPHeaders: BYPASS ? { 'x-vercel-protection-bypass': BYPASS, 'x-vercel-set-bypass-cookie': 'true' } : undefined,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, grep: /@responsive/ },
  ],
  webServer: REMOTE ? undefined : {
    command: 'e2e/fixtures/serve.sh',
    url: `http://127.0.0.1:${PORT}/api/meta`,
    env: { PORT: String(PORT) },
    reuseExistingServer: !CI,
    timeout: 120_000,
    stdout: 'pipe',
  },
});
