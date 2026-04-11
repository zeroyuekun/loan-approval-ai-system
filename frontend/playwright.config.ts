import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
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
    // Demo recording project — runs headed at 1280x720 with video always on
    // so the resulting .webm in test-results/ is portfolio-ready.
    // Invoke with: npm run demo:record
    {
      name: 'chromium-demo',
      use: {
        ...devices['Desktop Chrome'],
        headless: false,
        viewport: { width: 1280, height: 720 },
        video: { mode: 'on', size: { width: 1280, height: 720 } },
        // Slow everything by 300ms per action so the recording is readable
        // at normal playback speed rather than a blur of clicks.
        launchOptions: { slowMo: 300 },
      },
      // Retries would pollute test-results/ with multiple recordings.
      retries: 0,
    },
  ],
  // Don't start dev server — assume Docker Compose is running
});
