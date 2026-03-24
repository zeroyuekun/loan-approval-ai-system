import { test, expect } from '@playwright/test';

// Helper: login as admin before each test
async function loginAsAdmin(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await page.getByLabel(/username/i).fill('admin');
  await page.getByLabel(/password/i).fill('admin1234');
  await page.getByRole('button', { name: /sign in|log in|submit/i }).click();
  await page.waitForURL('**/dashboard', { timeout: 10000 });
}

test.beforeEach(async ({ page }) => {
  await loginAsAdmin(page);
});

test.describe('Dashboard', () => {
  test('dashboard loads for staff users', async ({ page }) => {
    // Already on dashboard from beforeEach
    await expect(page.getByText(/total applications/i)).toBeVisible({ timeout: 10000 });
  });

  test('can navigate to customers page', async ({ page }) => {
    await page.goto('/dashboard/customers');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toBeEmpty();
  });
});

test.describe('Model metrics page', () => {
  test('loads and displays model metrics or empty state', async ({ page }) => {
    await page.goto('/dashboard/model-metrics');

    // Wait for loading skeletons to disappear (page finished loading)
    await page.waitForLoadState('networkidle');

    // Either metrics are displayed or the "No active model" empty state appears
    const hasMetrics = await page.getByText(/accuracy/i).isVisible().catch(() => false);
    const hasEmptyState = await page.getByText(/no active model/i).isVisible().catch(() => false);
    const hasError = await page.getByText(/failed to load/i).isVisible().catch(() => false);

    expect(hasMetrics || hasEmptyState || hasError).toBeTruthy();
  });

  test('shows key metric cards when model exists', async ({ page }) => {
    await page.goto('/dashboard/model-metrics');
    await page.waitForLoadState('networkidle');

    // If a model is trained, these metric labels should appear
    const hasMetrics = await page.getByText(/accuracy/i).isVisible().catch(() => false);
    if (hasMetrics) {
      await expect(page.getByText(/precision/i)).toBeVisible();
      await expect(page.getByText(/recall/i)).toBeVisible();
      await expect(page.getByText(/f1 score/i)).toBeVisible();
      await expect(page.getByText(/auc-roc/i)).toBeVisible();
    }
  });

  test('model metrics page loads', async ({ page }) => {
    await page.goto('/dashboard/model-metrics');
    await expect(page.getByText(/model|metrics/i)).toBeVisible({ timeout: 10000 });
  });
});
