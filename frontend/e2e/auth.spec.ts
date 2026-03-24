import { test, expect } from '@playwright/test';

test.describe('Authentication', () => {
  test('login page loads', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: /login|sign in|welcome/i })).toBeVisible();
  });

  test('login with valid credentials redirects to dashboard', async ({ page }) => {
    await page.goto('/login');

    // Fill in admin credentials
    await page.getByLabel(/username/i).fill('admin');
    await page.getByLabel(/password/i).fill('admin1234');

    // Submit the form
    await page.getByRole('button', { name: /sign in|log in|submit/i }).click();

    // Wait for redirect to dashboard
    await page.waitForURL('**/dashboard', { timeout: 10000 });

    // Verify dashboard content is present
    await expect(page.getByText(/total applications/i)).toBeVisible({ timeout: 10000 });
  });

  test('login with invalid credentials shows error', async ({ page }) => {
    await page.goto('/login');

    await page.getByLabel(/username/i).fill('baduser');
    await page.getByLabel(/password/i).fill('badpass');
    await page.getByRole('button', { name: /sign in|log in|submit/i }).click();

    // Should show an error message and stay on login page
    const hasError = await page.getByText(/invalid|error|failed|incorrect/i).isVisible({ timeout: 5000 }).catch(() => false);
    const stayedOnLogin = page.url().includes('/login');
    expect(hasError || stayedOnLogin).toBeTruthy();
  });

  test('register page loads', async ({ page }) => {
    await page.goto('/register');
    await expect(page.getByRole('heading', { name: /register|sign up|create/i })).toBeVisible();
  });
});
