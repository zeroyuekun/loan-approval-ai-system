/**
 * API origin resolution and Content-Security-Policy construction.
 *
 * Pure functions so the proxy (src/proxy.ts), the axios client (lib/api.ts)
 * and their tests all derive the API origin and the CSP from one place.
 */

export const DEV_API_URL = 'http://localhost:8000/api/v1'
/** Same-origin API path, served by the reverse proxy / Ingress in front of the app. */
export const SAME_ORIGIN_API_URL = '/api/v1'

/**
 * The API base URL. `NEXT_PUBLIC_API_URL` is inlined at build time, so a
 * production build without it must not fall back to localhost: that would make
 * every visitor's browser call its own machine. It falls back to the
 * same-origin path instead. Dev and test keep the local backend default.
 */
export function resolveApiUrl(configured: string | undefined, nodeEnv: string | undefined): string {
  const value = configured?.trim()
  if (value) return value
  return nodeEnv === 'production' ? SAME_ORIGIN_API_URL : DEV_API_URL
}

/** Origin of an absolute URL, or null for a relative (same-origin) one. */
export function originOf(url: string): string | null {
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(url)) return null
  try {
    return new URL(url).origin
  } catch {
    return null
  }
}

/** Ingest origin of a Sentry DSN (`https://<key>@<host>/<project>`), or null. */
export function sentryOriginFromDsn(dsn: string | undefined): string | null {
  if (!dsn) return null
  return originOf(dsn)
}

interface CspOptions {
  nonce: string
  isDev: boolean
  /** Extra origins the browser may fetch from; null/empty entries are skipped. */
  connectOrigins: Array<string | null | undefined>
}

export function buildCsp({ nonce, isDev, connectOrigins }: CspOptions): string {
  // 'strict-dynamic' lets scripts loaded by a nonce-bearing script run (Next's
  // chunk loader) without allow-listing hosts. React needs eval in dev only.
  const scriptSrc = `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ''}`
  const connect = ["'self'", ...connectOrigins.filter((o): o is string => !!o)]

  return [
    "default-src 'self'",
    scriptSrc,
    // Inline style attributes (recharts, Tailwind-generated styles) still need
    // 'unsafe-inline'; style injection cannot run script.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src ${connect.join(' ')}`,
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')
}
