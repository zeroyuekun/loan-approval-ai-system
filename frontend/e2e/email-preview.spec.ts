import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

/**
 * Email-preview content regression (standalone).
 *
 * Loads byte-identical HTML snapshots shared with the unit tests and asserts
 * the rendered DOM contains the expected text, has zero <img> tags (Gmail
 * blocks them by default), and that the unsubscribe link is well-formed.
 * Python↔TS renderer drift is caught by the parity tests.
 */

const SNAPSHOT_DIR = path.resolve(__dirname, '../src/__tests__/fixtures/email_snapshots')

function loadSnapshot(stem: string): string {
  return fs.readFileSync(path.join(SNAPSHOT_DIR, `${stem}.html`), 'utf-8')
}

function wrapForBrowser(html: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><title>preview</title>
<style>body{margin:0;background:#f3f4f6;}</style>
</head><body>${html}</body></html>`
}

test.describe('email preview content regression', () => {
  test('approval email renders hero, loan card, and CTA', async ({ page }) => {
    await page.setContent(wrapForBrowser(loadSnapshot('approval_01_personal')))
    await expect(page.locator('h1')).toContainText(/Approved/i)
    // Section labels are visually uppercased via CSS text-transform but the DOM
    // text content is mixed-case. Assert against source case.
    await expect(page.locator('body')).toContainText(/Loan Details/i)
    await expect(page.locator('body')).toContainText(/Review & Sign/i)
    await expect(page.locator('body')).toContainText(/Congratulations/i)

    const imgCount = await page.locator('img').count()
    expect(imgCount).toBe(0)
  })

  test('denial email renders factor card, next-steps card, credit report card', async ({ page }) => {
    await page.setContent(wrapForBrowser(loadSnapshot('denial_01_serviceability')))
    await expect(page.locator('body')).toContainText(/Assessment Factors/i)
    await expect(page.locator('body')).toContainText(/What You Can Do/i)
    await expect(page.locator('body')).toContainText(/Free Credit Report/i)
    await expect(page.locator('body')).toContainText(/Call Sarah/i)

    const imgCount = await page.locator('img').count()
    expect(imgCount).toBe(0)
  })

  test('marketing email renders offer cards and unsubscribe footer', async ({ page }) => {
    await page.setContent(wrapForBrowser(loadSnapshot('marketing_01_three_options')))
    await expect(page.locator('body')).toContainText(/Option 1/i)
    await expect(page.locator('body')).toContainText(/Option 2/i)
    await expect(page.locator('body')).toContainText(/Option 3/i)
    await expect(page.locator('body')).toContainText(/Unsubscribe/i)
    await expect(page.locator('body')).toContainText(/Call Sarah/i)

    const imgCount = await page.locator('img').count()
    expect(imgCount).toBe(0)

    const unsubHref = await page.locator('a', { hasText: 'Unsubscribe' }).getAttribute('href')
    expect(unsubHref).toMatch(/^https:\/\/aussieloanai\.com\.au\/unsubscribe/)
  })

  test('marketing term-deposit variant shows FCS disclaimer', async ({ page }) => {
    await page.setContent(wrapForBrowser(loadSnapshot('marketing_04_term_deposit')))
    await expect(page.locator('body')).toContainText(/Financial Claims Scheme/)
  })

  test('marketing bonus-rate variant shows bonus-rate disclaimer', async ({ page }) => {
    await page.setContent(wrapForBrowser(loadSnapshot('marketing_05_bonus_rate')))
    await expect(page.locator('body')).toContainText(/Bonus rates apply/)
  })
})
