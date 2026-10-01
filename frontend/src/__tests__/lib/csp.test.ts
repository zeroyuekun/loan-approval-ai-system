import { buildCsp, originOf, resolveApiUrl, sentryOriginFromDsn } from '@/lib/csp'

function directive(csp: string, name: string): string | undefined {
  return csp
    .split(';')
    .map((d) => d.trim())
    .find((d) => d.startsWith(`${name} `) || d === name)
}

describe('resolveApiUrl', () => {
  it('uses the configured URL when one is set', () => {
    expect(resolveApiUrl('https://api.example.com/api/v1', 'production')).toBe('https://api.example.com/api/v1')
    expect(resolveApiUrl('/api/v1', 'production')).toBe('/api/v1')
  })

  it('falls back to same-origin /api/v1 in a production build with no URL configured', () => {
    // A published image must never point browsers at the visitor's own localhost.
    expect(resolveApiUrl(undefined, 'production')).toBe('/api/v1')
    expect(resolveApiUrl('   ', 'production')).toBe('/api/v1')
  })

  it('keeps the localhost backend as the dev default', () => {
    expect(resolveApiUrl(undefined, 'development')).toBe('http://localhost:8000/api/v1')
    expect(resolveApiUrl(undefined, 'test')).toBe('http://localhost:8000/api/v1')
  })
})

describe('originOf', () => {
  it('returns the origin of an absolute URL', () => {
    expect(originOf('https://api.example.com/api/v1')).toBe('https://api.example.com')
    expect(originOf('http://localhost:8000/api/v1')).toBe('http://localhost:8000')
  })

  it('returns null for a relative (same-origin) URL', () => {
    expect(originOf('/api/v1')).toBeNull()
  })
})

describe('sentryOriginFromDsn', () => {
  it('extracts the ingest origin and drops the public key', () => {
    expect(sentryOriginFromDsn('https://abc123@o42.ingest.us.sentry.io/789')).toBe('https://o42.ingest.us.sentry.io')
  })

  it('returns null when no DSN is configured or it is malformed', () => {
    expect(sentryOriginFromDsn(undefined)).toBeNull()
    expect(sentryOriginFromDsn('')).toBeNull()
    expect(sentryOriginFromDsn('not a dsn')).toBeNull()
  })
})

describe('buildCsp', () => {
  it('allows scripts only via the per-request nonce in production (no unsafe-inline)', () => {
    const csp = buildCsp({ nonce: 'abc', isDev: false, connectOrigins: [] })
    const scriptSrc = directive(csp, 'script-src')
    expect(scriptSrc).toContain("'nonce-abc'")
    expect(scriptSrc).toContain("'strict-dynamic'")
    expect(scriptSrc).not.toContain("'unsafe-inline'")
    expect(scriptSrc).not.toContain("'unsafe-eval'")
  })

  it('adds unsafe-eval only in development', () => {
    const csp = buildCsp({ nonce: 'abc', isDev: true, connectOrigins: [] })
    expect(directive(csp, 'script-src')).toContain("'unsafe-eval'")
  })

  it('derives connect-src from the given origins and skips empty ones', () => {
    const csp = buildCsp({
      nonce: 'abc',
      isDev: false,
      connectOrigins: ['https://api.example.com', null, 'https://o42.ingest.sentry.io'],
    })
    expect(directive(csp, 'connect-src')).toBe("connect-src 'self' https://api.example.com https://o42.ingest.sentry.io")
  })

  it('connect-src is self only for a same-origin API', () => {
    const csp = buildCsp({ nonce: 'abc', isDev: false, connectOrigins: [originOf('/api/v1')] })
    expect(directive(csp, 'connect-src')).toBe("connect-src 'self'")
  })

  it('keeps the existing framing, base-uri and form-action restrictions and blocks plugins', () => {
    const csp = buildCsp({ nonce: 'abc', isDev: false, connectOrigins: [] })
    expect(directive(csp, 'frame-ancestors')).toBe("frame-ancestors 'none'")
    expect(directive(csp, 'base-uri')).toBe("base-uri 'self'")
    expect(directive(csp, 'form-action')).toBe("form-action 'self'")
    expect(directive(csp, 'object-src')).toBe("object-src 'none'")
    expect(directive(csp, 'img-src')).toBe("img-src 'self' data:")
  })
})
