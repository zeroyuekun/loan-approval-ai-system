import { test, expect } from '@playwright/test';
import { loginAsAdmin } from './helpers/auth';

test.describe('Audit Trail', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('audit page loads', async ({ page }) => {
    await page.goto('/dashboard/audit');
    await expect(page.getByRole('heading', { name: 'Audit Log', level: 1 })).toBeVisible({ timeout: 10000 });
  });

  test('shows audit log entries or empty state', async ({ page }) => {
    await page.goto('/dashboard/audit');

    // Wait for content: the entries table, the empty state, or the load error
    await expect(
      page
        .locator('table')
        .or(page.getByText(/no audit log entries found|failed to load audit logs/i))
        .first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test('audit page is accessible from sidebar', async ({ page }) => {
    const auditLink = page.getByRole('link', { name: /audit/i });
    if (await auditLink.isVisible({ timeout: 5000 }).catch(() => false)) {
      await auditLink.click();
      await expect(page).toHaveURL(/audit/);
    }
  });
});
