import * as Sentry from '@sentry/nextjs'

// Next.js calls register() once per server runtime at startup. From
// @sentry/nextjs v8 onward this is the only place the server and edge
// configs are loaded; nothing else imports them.
export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    await import('../sentry.server.config')
  }
  if (process.env.NEXT_RUNTIME === 'edge') {
    await import('../sentry.edge.config')
  }
}

// Reports errors thrown while rendering server components and route handlers.
export const onRequestError = Sentry.captureRequestError
