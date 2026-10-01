import { NextRequest } from 'next/server'
import { proxy, config } from '@/proxy'

function nonceFrom(csp: string | null): string | undefined {
  return csp?.match(/'nonce-([^']+)'/)?.[1]
}

describe('proxy CSP', () => {
  it('sets a nonce-based CSP on the response and forwards it to the renderer', () => {
    const res = proxy(new NextRequest('http://localhost:3000/login'))
    const csp = res.headers.get('Content-Security-Policy')
    const nonce = nonceFrom(csp)

    expect(nonce).toBeTruthy()
    expect(csp).toContain("'strict-dynamic'")
    // Next.js reads the nonce from the *request* CSP header during SSR, so the
    // same policy has to be forwarded on the request (x-middleware-request-*).
    expect(res.headers.get('x-middleware-request-content-security-policy')).toBe(csp)
    expect(res.headers.get('x-middleware-request-x-nonce')).toBe(nonce)
  })

  it('generates a fresh nonce for every request', () => {
    const a = nonceFrom(proxy(new NextRequest('http://localhost:3000/login')).headers.get('Content-Security-Policy'))
    const b = nonceFrom(proxy(new NextRequest('http://localhost:3000/login')).headers.get('Content-Security-Policy'))
    expect(a).not.toBe(b)
  })

  it('runs on page routes, not on static assets', () => {
    const matcher = JSON.stringify(config.matcher)
    expect(matcher).toContain('_next/static')
    expect(matcher).toContain('_next/image')
  })
})

describe('proxy role routing (UX hint only)', () => {
  function withRole(path: string, role: string) {
    const req = new NextRequest(`http://localhost:3000${path}`)
    req.cookies.set('user_role', role)
    return proxy(req)
  }

  it('redirects a customer away from staff dashboard routes', () => {
    const res = withRole('/dashboard/applications', 'customer')
    expect(res.status).toBe(307)
    expect(res.headers.get('location')).toBe('http://localhost:3000/apply')
  })

  it('lets a customer reach their dashboard profile', () => {
    const res = withRole('/dashboard/profile', 'customer')
    expect(res.headers.get('location')).toBeNull()
  })

  it('redirects staff away from /apply', () => {
    const res = withRole('/apply', 'officer')
    expect(res.status).toBe(307)
    expect(res.headers.get('location')).toBe('http://localhost:3000/dashboard')
  })

  it('does not redirect unrelated routes', () => {
    const res = withRole('/login', 'customer')
    expect(res.headers.get('location')).toBeNull()
  })
})
