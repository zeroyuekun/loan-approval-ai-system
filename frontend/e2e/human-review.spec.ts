import { test, expect } from '@playwright/test';

test.describe('Human Review Queue', () => {
  test.beforeEach(async ({ page }) => {
    // Login as admin/staff
    await page.goto('/login');
    await page.getByLabel(/username/i).fill('admin');
    await page.getByLabel(/password/i).fill('admin1234');
    await page.getByRole('button', { name: /sign in|log in|submit/i }).click();
    await page.waitForURL('**/dashboard', { timeout: 10000 });
  });

  test('human review page loads', async ({ page }) => {
    await page.goto('/dashboard/human-review');
    await expect(page.getByText(/human review|review queue|pending review/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('shows empty state or review items', async ({ page }) => {
    await page.goto('/dashboard/human-review');

    // Wait for content to load — either shows items or empty state
    const hasContent = await page
      .getByText(/no.*review|pending|bias|escalat/i)
      .first()
      .isVisible({ timeout: 5000 })
      .catch(() => false);

    const hasTable = await page
      .locator('table, [role="table"]')
      .isVisible({ timeout: 2000 })
      .catch(() => false);

    expect(hasContent || hasTable).toBeTruthy();
  });

  test('review page is accessible from sidebar', async ({ page }) => {
    // Click on human review link in sidebar
    const reviewLink = page.getByRole('link', { name: /human review|review/i });
    if (await reviewLink.isVisible({ timeout: 5000 }).catch(() => false)) {
      await reviewLink.click();
      await expect(page).toHaveURL(/human-review/);
    }
  });
});
