import * as Sentry from '@sentry/nextjs'
import { sentryBaseOptions } from '@/lib/sentryScrub'

// Runs in the browser before the app becomes interactive. Replaces
// sentry.client.config.ts, which only the webpack plugin injected and which
// never ran under Turbopack (the Next 16 default), so captureException in
// ErrorBoundary was a no-op.
const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN

if (dsn) {
  Sentry.init(sentryBaseOptions(dsn))
}

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart
