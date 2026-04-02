import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.describe('Accessibility', () => {
  test('login page has no critical accessibility violations', async ({ page }) => {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious',
    );
    expect(critical).toEqual([]);
  });

  test('dashboard has no critical accessibility violations', async ({ page }) => {
    // Login first
    await page.goto('/login');
    await page.getByLabel(/username/i).fill('admin');
    await page.getByLabel(/password/i).fill('admin1234');
    await page.getByRole('button', { name: /sign in|log in|submit/i }).click();
    await page.waitForURL('**/dashboard', { timeout: 10000 });
    await page.waitForLoadState('networkidle');

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious',
    );
    expect(critical).toEqual([]);
  });

  test('application form has no critical accessibility violations', async ({ page }) => {
    // Login as customer
    await page.goto('/login');
    await page.getByLabel(/username/i).fill('nevillezeng');
    await page.getByLabel(/password/i).fill('admin1234');
    await page.getByRole('button', { name: /sign in|log in|submit/i }).click();
    await page.waitForURL('**/apply', { timeout: 10000 });

    await page.goto('/apply/new');
    await page.waitForLoadState('networkidle');

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious',
    );
    expect(critical).toEqual([]);
  });

  test('rights page has no critical accessibility violations', async ({ page }) => {
    await page.goto('/rights');
    await page.waitForLoadState('networkidle');

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious',
    );
    expect(critical).toEqual([]);
  });
});
