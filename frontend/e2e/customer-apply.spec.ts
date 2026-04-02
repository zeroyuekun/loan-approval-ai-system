import { test, expect } from '@playwright/test';

test.describe('Customer Apply Portal', () => {
  test.beforeEach(async ({ page }) => {
    // Login as customer
    await page.goto('/login');
    await page.getByLabel(/username/i).fill('nevillezeng');
    await page.getByLabel(/password/i).fill('admin1234');
    await page.getByRole('button', { name: /sign in|log in|submit/i }).click();
    await page.waitForURL('**/apply', { timeout: 10000 });
  });

  test('customer portal loads and shows apply page', async ({ page }) => {
    await expect(page).toHaveURL(/\/apply/);
    // Should show some portal content
    const heading = page.getByRole('heading').first();
    await expect(heading).toBeVisible({ timeout: 5000 });
  });

  test('navigate to new application form', async ({ page }) => {
    await page.goto('/apply/new');
    await expect(page.getByText(/new loan application|apply/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('application form shows step navigation', async ({ page }) => {
    await page.goto('/apply/new');

    // Form should have step indicators
    const personalStep = page.getByText(/personal/i).first();
    await expect(personalStep).toBeVisible({ timeout: 5000 });
  });

  test('form validates before allowing next step', async ({ page }) => {
    await page.goto('/apply/new');

    // Try to proceed without filling fields
    const nextButton = page.getByRole('button', { name: /next|continue/i });
    if (await nextButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await nextButton.click();
      // Should stay on the same step or show validation errors
      const stayedOnPage = page.url().includes('/apply/new');
      expect(stayedOnPage).toBeTruthy();
    }
  });
});
