import * as Sentry from '@sentry/nextjs'
import { sentryBaseOptions } from './src/lib/sentryScrub'

// Loaded from src/instrumentation.ts register() on the edge runtime.
const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN

if (dsn) {
  Sentry.init(sentryBaseOptions(dsn))
}
