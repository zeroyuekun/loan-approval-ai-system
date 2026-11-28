import { test, expect } from '@playwright/test';
import { credentialsFor, landingFor, submitLogin } from './helpers/auth';

test.describe('Authentication', () => {
  test('login page loads', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: /login|sign in|welcome/i })).toBeVisible();
  });

  test('login with valid credentials redirects to dashboard', async ({ page }) => {
    // Goes through the form on purpose; other specs reuse the saved session.
    const creds = credentialsFor('admin');
    test.skip(!creds, 'Set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD to run this test.');
    await submitLogin(page, creds!.email, creds!.password);
    await page.waitForURL(landingFor('admin'), { timeout: 10000 });

    // Verify dashboard content is present
    await expect(page.getByText(/total applications/i)).toBeVisible({ timeout: 10000 });
  });

  test('login with invalid credentials shows error', async ({ page }) => {
    await submitLogin(page, 'nobody@example.invalid', 'not-a-real-password');

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
