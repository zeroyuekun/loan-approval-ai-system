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

// ComparisonRate integration is covered by unit tests
// (src/__tests__/comparison-rate.test.tsx) and by the
// RepaymentCalculator test suite. An e2e case here would require a
// public preview route or an authenticated helper to reach /apply/new,
// which is out of scope for this PR. Revisit when either exists.
