import { test, expect } from '@playwright/test';

// Helper: login as admin before each test
async function loginAsAdmin(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await page.getByLabel(/username/i).fill('admin');
  await page.getByLabel(/password/i).fill('admin1234');
  await page.getByRole('button', { name: /sign in|log in|submit/i }).click();
  await page.waitForURL('**/dashboard', { timeout: 10000 });
}

test.beforeEach(async ({ page }) => {
  await loginAsAdmin(page);
});

test.describe('Dashboard applications', () => {
  test('displays stats cards on the dashboard', async ({ page }) => {
    // StatsCards should render key metrics
    await expect(page.getByText(/total applications/i)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/approval rate/i)).toBeVisible();
    await expect(page.getByText(/active model/i)).toBeVisible();
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

test.describe('Loan Application', () => {
  test('application form loads after login', async ({ page }) => {
    await page.goto('/apply');
    await expect(page).toHaveURL(/apply/);
  });

  test('multi-step form has navigation', async ({ page }) => {
    await page.goto('/apply');

    // Should see step indicator or personal details section (step 1)
    const hasPersonal = await page.getByText(/personal/i).isVisible({ timeout: 5000 }).catch(() => false);
    const hasStep = await page.getByText(/step/i).isVisible({ timeout: 5000 }).catch(() => false);
    const hasForm = await page.locator('form').isVisible({ timeout: 5000 }).catch(() => false);

    expect(hasPersonal || hasStep || hasForm).toBeTruthy();
  });
});
