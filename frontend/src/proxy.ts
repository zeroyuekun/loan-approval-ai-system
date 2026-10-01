import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { buildCsp, originOf, resolveApiUrl, sentryOriginFromDsn } from '@/lib/csp'

const API_URL = resolveApiUrl(process.env.NEXT_PUBLIC_API_URL, process.env.NODE_ENV)

/** Role-based redirect for page routes, or null to continue. */
function roleRedirect(request: NextRequest): URL | null {
  const { pathname } = request.nextUrl

  // NOTE: This cookie is a UX hint only — it is NOT a security boundary.
  // All authorization is enforced server-side via JWT + role checks in Django.
  // A spoofed cookie only changes client routing, not data access.
  const userRole = request.cookies.get('user_role')?.value

  // If customer tries to access any /dashboard route (except their profile), redirect to /apply
  if (pathname.startsWith('/dashboard') && userRole === 'customer' && !pathname.startsWith('/dashboard/profile')) {
    return new URL('/apply', request.url)
  }

  // If non-customer tries to access /apply, redirect to /dashboard
  if (pathname.startsWith('/apply') && userRole && userRole !== 'customer') {
    return new URL('/dashboard', request.url)
  }

  return null
}

export function proxy(request: NextRequest) {
  // A fresh nonce per request. Next.js reads it from the request's CSP header
  // during server rendering and stamps it on its own inline and chunk scripts
  // (the RSC flight data is streamed as inline <script> tags). A static CSP
  // from next.config headers() never carries a nonce, so without this the
  // production build cannot hydrate.
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64')
  const csp = buildCsp({
    nonce,
    isDev: process.env.NODE_ENV === 'development',
    // The API (when on another origin) and the Sentry ingest host
    connectOrigins: [originOf(API_URL), sentryOriginFromDsn(process.env.NEXT_PUBLIC_SENTRY_DSN)],
  })

  const redirectTo = roleRedirect(request)
  if (redirectTo) {
    const redirect = NextResponse.redirect(redirectTo)
    redirect.headers.set('Content-Security-Policy', csp)
    return redirect
  }

  const requestHeaders = new Headers(request.headers)
  requestHeaders.set('x-nonce', nonce)
  requestHeaders.set('Content-Security-Policy', csp)

  const response = NextResponse.next({ request: { headers: requestHeaders } })
  response.headers.set('Content-Security-Policy', csp)
  return response
}

export const config = {
  // Every page route needs a nonce, so this runs on everything except
  // build assets and static files (which carry no inline script).
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|gif|svg|webp|ico|txt|xml|webmanifest)$).*)',
  ],
}
