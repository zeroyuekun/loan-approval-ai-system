import type { Event } from '@sentry/nextjs'

/** Request headers that carry credentials or session state. */
const SENSITIVE_HEADERS = new Set(['cookie', 'set-cookie', 'authorization', 'x-csrftoken', 'x-csrf-token'])

/**
 * Remove personal and credential data before an event leaves the browser or
 * server. Loan applications carry income, credit and identity data, so request
 * bodies, cookies and query strings are never sent, and the user is reduced
 * to its opaque id.
 */
export function scrubEvent<T extends Event>(event: T): T {
  if (event.request) {
    const { data: _data, cookies: _cookies, query_string: _qs, headers, ...rest } = event.request
    event.request = rest
    if (headers) {
      event.request.headers = Object.fromEntries(
        Object.entries(headers).filter(([name]) => !SENSITIVE_HEADERS.has(name.toLowerCase())),
      )
    }
  }
  if (event.user) {
    event.user = event.user.id !== undefined ? { id: event.user.id } : {}
  }
  return event
}

/** Options shared by the client, server and edge Sentry.init calls. */
export function sentryBaseOptions(dsn: string) {
  return {
    dsn,
    tracesSampleRate: 0.1,
    // Never attach IP addresses, cookies or request bodies automatically.
    sendDefaultPii: false,
    beforeSend: scrubEvent,
    beforeSendTransaction: scrubEvent,
  }
}
