/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV !== 'production'
const apiOrigin = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8500/api/v1').replace(/\/api\/v1\/?$/, '')

const nextConfig = {
  output: 'standalone',
  async headers() {
    // In development, Next.js needs 'unsafe-eval' and 'unsafe-inline' for HMR.
    // In production, these are removed for strict CSP.
    const scriptSrc = isDev
      ? "script-src 'self' 'unsafe-eval' 'unsafe-inline'"
      : "script-src 'self'"

    return [
      {
        source: '/(.*)',
        headers: [
          {
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
              scriptSrc,
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data:",
              `connect-src 'self' ${apiOrigin}`,
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
            ].join('; '),
          },
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
module.exports = nextConfig
