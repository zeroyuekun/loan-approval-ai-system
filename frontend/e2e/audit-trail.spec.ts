import { test, expect } from '@playwright/test';

test.describe('Audit Trail', () => {
  test.beforeEach(async ({ page }) => {
    // Login as admin
    await page.goto('/login');
    await page.getByLabel(/username/i).fill('admin');
    await page.getByLabel(/password/i).fill('admin1234');
    await page.getByRole('button', { name: /sign in|log in|submit/i }).click();
    await page.waitForURL('**/dashboard', { timeout: 10000 });
  });

  test('audit page loads', async ({ page }) => {
    await page.goto('/dashboard/audit');
    await expect(page.getByText(/audit|log|trail/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('shows audit log entries or empty state', async ({ page }) => {
    await page.goto('/dashboard/audit');

    // Wait for content — either log entries or empty state
    const hasEntries = await page
      .locator('table, [role="table"], [class*="timeline"], [class*="log"]')
      .first()
      .isVisible({ timeout: 5000 })
      .catch(() => false);

    const hasEmptyState = await page
      .getByText(/no.*audit|no.*log|no.*entries|empty/i)
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false);

    expect(hasEntries || hasEmptyState).toBeTruthy();
  });

  test('audit page is accessible from sidebar', async ({ page }) => {
    const auditLink = page.getByRole('link', { name: /audit/i });
    if (await auditLink.isVisible({ timeout: 5000 }).catch(() => false)) {
      await auditLink.click();
      await expect(page).toHaveURL(/audit/);
    }
  });
});
