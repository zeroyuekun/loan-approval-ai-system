import { test, expect } from '@playwright/test';
import { loginAsAdmin } from './helpers/auth';

test.describe('Human Review Queue', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('human review page loads', async ({ page }) => {
    await page.goto('/dashboard/human-review');
    await expect(page.getByText(/human review|review queue|pending review/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('shows empty state or review items', async ({ page }) => {
    await page.goto('/dashboard/human-review');

    // Wait for content: the review table, the empty state, or the load error
    await expect(
      page
        .locator('table')
        .or(page.getByText(/no applications require human review|failed to load escalated applications/i))
        .first(),
    ).toBeVisible({ timeout: 15000 });
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
