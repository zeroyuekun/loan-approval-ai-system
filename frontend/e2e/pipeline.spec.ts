import { test, expect } from '@playwright/test';
import { loginAsAdmin } from './helpers/auth';

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

    // A loaded model shows the tab strip (plain buttons); otherwise a notice.
    await expect(
      page
        .getByRole('button', { name: /fairness by group/i })
        .or(page.getByText(/no active model found|failed to load model metrics/i)),
    ).toBeVisible({ timeout: 15000 });
  });

  test('shows key metric cards when model exists', async ({ page }) => {
    await page.goto('/dashboard/model-metrics');

    const technicalTab = page.getByRole('button', { name: /technical details/i });
    const noModel = page.getByText(/no active model found/i);
    await expect(technicalTab.or(noModel)).toBeVisible({ timeout: 15000 });
    test.skip(await noModel.isVisible(), 'No trained model in this environment.');

    // The headline scores sit in the admin-only Technical details tab.
    await technicalTab.click();
    for (const label of ['AUC-ROC', 'Accuracy', 'Precision', 'Recall', 'F1 Score']) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }
  });

  test('model metrics page loads', async ({ page }) => {
    await page.goto('/dashboard/model-metrics');
    await expect(page.getByRole('heading', { name: 'Model Metrics' })).toBeVisible({ timeout: 10000 });
  });
});
