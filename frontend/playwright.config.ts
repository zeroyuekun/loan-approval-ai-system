import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // Signs in once per role so specs stay under the backend login throttle.
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // One worker everywhere: the specs share one session per role, and the
  // backend throttles each user to 60 requests a minute. Parallel workers
  // exceed that and pages fail to load with HTTP 429.
  workers: 1,
  reporter: 'html',
  timeout: 30000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    headless: true,
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  // Don't start dev server — assume Docker Compose is running
});
