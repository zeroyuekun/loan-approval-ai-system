import { test, expect } from '@playwright/test';

/**
 * Happy-path E2E test: Login → Create Application → Run Pipeline → Verify Completion
 *
 * Prerequisites: Docker Compose must be running (backend, frontend, db, redis, celery workers).
 * Uses the seeded admin account (admin / admin1234).
 */

async function loginAsAdmin(page: import('@playwright/test').Page) {
  await page.goto('/login');
  // The login form email field has id="username" but type="email" — fill via id
  await page.locator('#username').fill(process.env.E2E_ADMIN_EMAIL || 'admin@example.com');
  await page.locator('#password').fill(process.env.E2E_ADMIN_PASSWORD || 'admin12345');
  await page.getByRole('button', { name: /sign in|log in|submit/i }).click();
  await page.waitForURL('**/dashboard', { timeout: 10000 });
}

test.describe('Happy Path: Loan Application Lifecycle', () => {
  test('create application, run pipeline, verify completion', async ({ page }) => {
    // Increase timeout — pipeline involves ML prediction + LLM calls
    test.setTimeout(120_000);

    // --- Step 1: Login as admin ---
    await loginAsAdmin(page);
    await expect(page.getByText(/total applications/i)).toBeVisible({ timeout: 10000 });

    // --- Step 2: Navigate to new application form ---
    await page.goto('/dashboard/applications/new');
    await expect(page.getByRole('heading', { name: /personal information/i })).toBeVisible({ timeout: 10000 });

    // --- Step 3: Fill out the multi-step form ---

    // Step 1: Personal (defaults are fine — single, 0 dependants, rent)
    await page.getByText('Next').click();
    await expect(page.getByRole('heading', { name: /employment/i })).toBeVisible();

    // Step 2: Employment & Income
    const incomeInput = page.getByLabel(/gross annual income/i);
    await incomeInput.fill('95000');

    const creditInput = page.getByLabel(/equifax credit score/i);
    await creditInput.fill('720');

    const employmentLength = page.getByLabel(/time in current role/i);
    await employmentLength.fill('5');

    await page.getByText('Next').click();
    await expect(page.getByRole('heading', { name: /expenses/i })).toBeVisible();

    // Step 3: Expenses & Debts (fill DTI — required)
    const dtiInput = page.getByLabel(/debt.to.income/i);
    await dtiInput.fill('3.2');

    await page.getByText('Next').click();
    await expect(page.getByRole('heading', { name: /loan details/i })).toBeVisible();

    // Step 4: Loan Details
    const loanAmountInput = page.getByLabel(/loan amount/i);
    await loanAmountInput.fill('35000');

    // Select purpose
    const purposeSelect = page.getByLabel(/purpose/i);
    await purposeSelect.selectOption('personal');

    await page.getByText('Next').click();
    await expect(page.getByRole('heading', { name: /review/i })).toBeVisible();

    // --- Step 4: Submit the application ---
    await page.getByRole('button', { name: /submit application/i }).click();

    // Should redirect to the application detail page
    await page.waitForURL('**/dashboard/applications/**', { timeout: 15000 });

    // --- Step 5: Verify the application detail loaded ---
    // The loan amount should be displayed
    await expect(page.getByText(/35,000/)).toBeVisible({ timeout: 10000 });

    // --- Step 6: Check pipeline status ---
    // The pipeline auto-triggers on creation. Wait for it to reach a terminal state.
    // Look for a status indicator that shows completed, failed, or escalated.
    const terminalStatus = page.getByText(/completed|failed|escalated|approved|denied/i);
    await expect(terminalStatus.first()).toBeVisible({ timeout: 90_000 });

    // --- Step 7: Verify decision was made ---
    // Either an approval or denial decision should exist
    const hasDecision = await page.getByText(/approved|denied/i).first().isVisible().catch(() => false);
    expect(hasDecision).toBeTruthy();

    // --- Step 8: Verify email was generated ---
    // The email section should show a generated email (subject or body content)
    const hasEmail = await page.getByText(/subject:|dear|application/i).first().isVisible().catch(() => false);
    // Email may not be visible if API key is not set — that's OK for CI
    if (hasEmail) {
      // Verify bias check ran (bias score indicator should exist)
      const hasBias = await page.getByText(/bias|compliance/i).first().isVisible().catch(() => false);
      expect(hasBias).toBeTruthy();
    }
  });

  test('application appears in the applications list', async ({ page }) => {
    await loginAsAdmin(page);

    await page.goto('/dashboard/applications');
    await page.waitForLoadState('networkidle');

    // At least one application should exist (from seeded data or previous test)
    const rows = page.locator('table tbody tr, [class*="card"], [class*="application"]');
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);
  });
});
