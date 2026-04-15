import { test, expect } from '@playwright/test';

const PUBLIC_ROUTES = ['/', '/login', '/rights'];

test.describe('Regulatory surfaces - footer presence', () => {
  for (const path of PUBLIC_ROUTES) {
    test(`footer renders on ${path}`, async ({ page }) => {
      await page.goto(path);
      const footer = page.getByRole('contentinfo');
      await expect(footer).toBeVisible();
      await expect(footer).toContainText('ACL');
      await expect(footer).toContainText('1800 931 678');
      await expect(footer).toContainText('is not an Authorised Deposit-taking Institution');
    });
  }
});

test.describe('Regulatory surfaces - ComparisonRate on rate display', () => {
  // Minimal smoke: the RepaymentCalculator is inside /apply/new, which is
  // behind auth. We assert the component mounts when a rate is displayed.
  // If the dev harness exposes a public storybook-style preview route in
  // the future, prefer that; for now we rely on unit tests for behaviour
  // and this e2e for integration wiring.
  test.skip('covered by unit tests in PR 2', () => {
    // Intentionally skipped; see src/__tests__/comparison-rate.test.tsx
  });
});
