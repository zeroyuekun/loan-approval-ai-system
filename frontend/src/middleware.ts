import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // NOTE: This cookie is a UX hint only — it is NOT a security boundary.
  // All authorization is enforced server-side via JWT + role checks in Django.
  // A spoofed cookie only changes client routing, not data access.
  const userRole = request.cookies.get('user_role')?.value

  // If customer tries to access any /dashboard route (except their profile), redirect to /apply
  if (pathname.startsWith('/dashboard') && userRole === 'customer' && !pathname.startsWith('/dashboard/profile')) {
    return NextResponse.redirect(new URL('/apply', request.url))
  }

  // If non-customer tries to access /apply, redirect to /dashboard
  if (pathname.startsWith('/apply') && userRole && userRole !== 'customer') {
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/dashboard/:path*', '/apply/:path*'],
}
