import fs from 'node:fs'
import path from 'node:path'
import { test, type Page } from '@playwright/test'

/**
 * Shared sign-in helpers for the Playwright specs.
 *
 * The login form takes an email address and a password. Credentials come
 * from the environment, never from the spec files:
 *
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD        an admin or officer account
 *   E2E_CUSTOMER_EMAIL / E2E_CUSTOMER_PASSWORD  a customer account
 *
 * global-setup.ts signs in once per role and saves the session cookies;
 * loginAs() loads them into the test's browser context. When a pair is
 * unset, the tests that need it are skipped with a message that names the
 * missing variables, so a run without credentials reports "skipped"
 * instead of failing on a login timeout.
 */

export type E2ERole = 'admin' | 'customer'

export const E2E_ROLES: readonly E2ERole[] = ['admin', 'customer']

const ROLE_ENV: Record<E2ERole, { email: string; password: string; landing: string }> = {
  admin: { email: 'E2E_ADMIN_EMAIL', password: 'E2E_ADMIN_PASSWORD', landing: '**/dashboard' },
  customer: { email: 'E2E_CUSTOMER_EMAIL', password: 'E2E_CUSTOMER_PASSWORD', landing: '**/apply' },
}

export interface Credentials {
  email: string
  password: string
}

/** Returns the credentials for a role, or null when either variable is unset. */
export function credentialsFor(role: E2ERole): Credentials | null {
  const names = ROLE_ENV[role]
  const email = process.env[names.email]?.trim()
  const password = process.env[names.password]
  if (!email || !password) return null
  return { email, password }
}

/** URL glob of the page a role lands on after signing in. */
export function landingFor(role: E2ERole): string {
  return ROLE_ENV[role].landing
}

/** Where global-setup.ts saves the signed-in session for a role. */
export function storageStatePath(role: E2ERole): string {
  return path.join(__dirname, '..', '.auth', `${role}.json`)
}

/** Fills and submits the login form. Does not wait for a redirect. */
export async function submitLogin(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login')
  // Wait for React to hydrate. A click before hydration submits the form
  // natively (GET /login?) and the sign-in request is never sent.
  await page.waitForLoadState('networkidle')
  await page.getByLabel('Email', { exact: true }).fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: /sign in/i }).click()
}

/**
 * Starts the test signed in as the given role, on that role's landing
 * page. Skips the current test when the role's credentials are not set.
 */
export async function loginAs(page: Page, role: E2ERole): Promise<void> {
  const names = ROLE_ENV[role]
  test.skip(!credentialsFor(role), `Set ${names.email} and ${names.password} to run this test.`)
  const statePath = storageStatePath(role)
  if (!fs.existsSync(statePath)) {
    throw new Error(`${statePath} is missing. global-setup.ts writes it; run the suite through playwright.config.ts.`)
  }
  const state = JSON.parse(fs.readFileSync(statePath, 'utf-8'))
  await page.context().addCookies(state.cookies)
  await page.goto(names.landing.replace('**', ''))
  await page.waitForURL(names.landing, { timeout: 10000 })
}

export const loginAsAdmin = (page: Page) => loginAs(page, 'admin')
export const loginAsCustomer = (page: Page) => loginAs(page, 'customer')
