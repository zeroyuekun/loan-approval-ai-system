import { test, expect, type Page } from '@playwright/test';
import { loginAsAdmin, loginAsCustomer } from './helpers/auth';

test.describe('Dashboard applications', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('displays stats cards on the dashboard', async ({ page }) => {
    // StatsCards renders these four titles
    await expect(page.getByText('Total Applications', { exact: true })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Approval Rate', { exact: true })).toBeVisible();
    await expect(page.getByText("Today's Decisions", { exact: true })).toBeVisible();
    await expect(page.getByText('LLM Spend', { exact: true })).toBeVisible();
  });

  test('shows recent applications section', async ({ page }) => {
    // The RecentApplications component should render
    await expect(page.getByText(/recent applications/i)).toBeVisible({ timeout: 10000 });
  });

  test('can navigate to the applications list', async ({ page }) => {
    // Navigate via sidebar or direct URL
    await page.goto('/dashboard/applications');
    await page.waitForLoadState('networkidle');

    // The page should load without error
    await expect(page.locator('body')).not.toBeEmpty();
  });
});

// The /apply portal is for customers; staff are redirected to /dashboard.
test.describe('Loan Application', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsCustomer(page);
  });

  // A customer with an incomplete profile sees a "complete your profile"
  // notice instead of the form. Either one means the page loaded.
  async function openApplicationForm(page: Page) {
    await page.goto('/apply/new');
    const next = page.getByRole('button', { name: 'Next', exact: true });
    const profileGate = page.getByText('Complete Your Profile First');
    await expect(next.or(profileGate)).toBeVisible({ timeout: 10000 });
    return { next, profileGate };
  }

  test('application form loads after login', async ({ page }) => {
    await openApplicationForm(page);
    await expect(page.getByRole('heading', { name: 'New Loan Application' })).toBeVisible();
  });

  test('multi-step form has navigation', async ({ page }) => {
    const { next, profileGate } = await openApplicationForm(page);
    test.skip(await profileGate.isVisible(), 'The E2E customer profile is incomplete, so the form is not shown.');
    await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeDisabled();
    await expect(next).toBeEnabled();
  });
});
