const { withSentryConfig } = require('@sentry/nextjs')

/** @type {import('next').NextConfig} */
const nextConfig = {
  // output: 'standalone' removed (H30) — the Dockerfile uses `npm start`
  // (standard Next.js server) which requires full node_modules, not the
  // standalone bundle. Setting output:'standalone' caused the build to emit
  // .next/standalone/ which was silently discarded, wasting build time.
  async headers() {
    // Content-Security-Policy is NOT set here: it needs a per-request nonce
    // so Next's inline scripts can run, which only the proxy can generate
    // (src/proxy.ts, policy built in src/lib/csp.ts).
    return [
      {
        source: '/(.*)',
        headers: [
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=()',
          },
        ],
      },
    ]
  },
}
module.exports = process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(nextConfig, {
      silent: true,
      disableLogger: true,
    })
  : nextConfig
