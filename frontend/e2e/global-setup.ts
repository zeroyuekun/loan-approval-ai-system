import fs from 'node:fs'
import path from 'node:path'
import { chromium, type FullConfig } from '@playwright/test'
import { E2E_ROLES, credentialsFor, storageStatePath, submitLogin, landingFor } from './helpers/auth'

/**
 * Signs in once per role and saves the session cookies to e2e/.auth/.
 *
 * The backend allows 5 login attempts per minute per IP, so signing in
 * through the form in every test would trip the throttle (HTTP 429) as
 * soon as the workers run in parallel. Specs reuse these sessions through
 * loginAs() instead. A role whose credentials are unset gets no file, and
 * its tests skip.
 */
export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use.baseURL ?? 'http://localhost:3000'
  const roles = E2E_ROLES.filter((role) => credentialsFor(role))
  for (const role of E2E_ROLES) fs.rmSync(storageStatePath(role), { force: true })
  if (roles.length === 0) return

  const browser = await chromium.launch()
  try {
    for (const role of roles) {
      const creds = credentialsFor(role)!
      const context = await browser.newContext({ baseURL })
      const page = await context.newPage()
      await submitLogin(page, creds.email, creds.password)
      try {
        await page.waitForURL(landingFor(role), { timeout: 15000 })
      } catch {
        const alert = await page.locator('.text-destructive').first().textContent().catch(() => null)
        throw new Error(
          `E2E sign-in as ${role} (${creds.email}) did not reach ${landingFor(role)}. ` +
            `Page said: ${alert?.trim() || 'nothing'}. Check the credentials, and wait a minute if the login throttle tripped.`,
        )
      }
      fs.mkdirSync(path.dirname(storageStatePath(role)), { recursive: true })
      await context.storageState({ path: storageStatePath(role) })
      await context.close()
    }
  } finally {
    await browser.close()
  }
}
