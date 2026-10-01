/**
 * Client-side session hints.
 *
 * The real session lives in HttpOnly cookies set by the backend. These are
 * only the non-PII markers the UI reads: a sessionStorage copy of role +
 * username for instant render, and a `user_role` cookie that middleware.ts
 * reads for route gating. Shared by AuthProvider and the axios interceptor
 * (which runs outside React and cannot use the hook).
 */

const SESSION_USER_KEY = 'user'

export function setRoleCookie(role: string): void {
  const secure = window.location.hostname !== 'localhost' ? ';Secure' : ''
  document.cookie = `user_role=${role};path=/;max-age=${60 * 60 * 24 * 30};SameSite=Lax${secure}`
}

export function readSessionUser(): string | null {
  return sessionStorage.getItem(SESSION_USER_KEY)
}

/**
 * Store only role + username. id and email are intentionally excluded to
 * minimise same-tab JS exposure.
 */
export function storeSessionUser(user: { role: string; username: string }): void {
  sessionStorage.setItem(SESSION_USER_KEY, JSON.stringify({ role: user.role, username: user.username }))
  setRoleCookie(user.role)
}

export function clearSession(): void {
  if (typeof sessionStorage !== 'undefined') {
    sessionStorage.removeItem(SESSION_USER_KEY)
  }
  if (typeof document !== 'undefined') {
    // max-age=0 expires the role cookie immediately
    document.cookie = 'user_role=;path=/;max-age=0'
  }
}
