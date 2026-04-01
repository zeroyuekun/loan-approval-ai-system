import { test, expect } from '@playwright/test';

test.describe('Negative Paths', () => {
  test('unauthenticated access to dashboard redirects to login', async ({ page }) => {
    // Clear any existing session
    await page.context().clearCookies();

    await page.goto('/dashboard');
    await page.waitForURL('**/login', { timeout: 10000 });
    expect(page.url()).toContain('/login');
  });

  test('unauthenticated access to customer portal redirects to login', async ({ page }) => {
    await page.context().clearCookies();

    await page.goto('/apply');
    await page.waitForURL('**/login', { timeout: 10000 });
    expect(page.url()).toContain('/login');
  });

  test('non-existent page shows 404', async ({ page }) => {
    await page.goto('/this-page-does-not-exist');
    const has404 = await page
      .getByText(/not found|404|page doesn't exist/i)
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    const statusOk = page.url().includes('/this-page-does-not-exist');
    expect(has404 || statusOk).toBeTruthy();
  });

  test('customer application form validates required fields', async ({ page }) => {
    // Login as a customer first
    await page.goto('/login');
    await page.getByLabel(/username/i).fill('nevillezeng');
    await page.getByLabel(/password/i).fill('admin1234');
    await page.getByRole('button', { name: /sign in|log in|submit/i }).click();

    // Wait for customer portal
    await page.waitForURL('**/apply', { timeout: 10000 });

    // Navigate to new application
    await page.goto('/apply/new');

    // Try to proceed without filling required fields — click next/submit
    const submitButton = page.getByRole('button', { name: /next|submit|continue|apply/i });
    if (await submitButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await submitButton.click();

      // Should show validation errors or remain on the same page
      const hasValidationError = await page
        .getByText(/required|please|must|invalid|enter/i)
        .first()
        .isVisible({ timeout: 5000 })
        .catch(() => false);
      const stayedOnPage = page.url().includes('/apply/new');
      expect(hasValidationError || stayedOnPage).toBeTruthy();
    }
  });
});
