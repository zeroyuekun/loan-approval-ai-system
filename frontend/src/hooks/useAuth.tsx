'use client'

import { useState, useEffect, useCallback, ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { AuthContext, type LoginResult } from '@/lib/auth'
import api, { authApi, type RegisterPayload } from '@/lib/api'
import { clearSession, readSessionUser, setRoleCookie, storeSessionUser } from '@/lib/session'
import { clearForeignDraft, resetClientState } from '@/lib/clientState'
import { User } from '@/types'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const router = useRouter()
  const queryClient = useQueryClient()

  const fetchProfile = useCallback(async () => {
    try {
      const { data } = await authApi.getProfile()
      setUser(data)
      storeSessionUser(data)
      return true
    } catch {
      setUser(null)
      clearSession()
      return false
    }
  }, [])

  // On mount, try to restore session from HttpOnly cookies
  useEffect(() => {
    // Load cached user from sessionStorage for instant render
    const cached = readSessionUser()
    if (cached) {
      try {
        const parsed = JSON.parse(cached)
        // Must run after hydration: the provider is server-prerendered and the
        // server has no sessionStorage, so a useState initializer would mismatch.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setUser(parsed)
        setRoleCookie(parsed.role)
      } catch {}
    }
    // Verify with server (cookies are sent automatically)
    fetchProfile().finally(() => setIsLoading(false))
  }, [fetchProfile])

  const login = useCallback(async (username: string, password: string, otpToken?: string): Promise<LoginResult> => {
    // Ensure we have a CSRF token before the login POST
    await authApi.getCsrfToken()
    const { data } = await authApi.login(otpToken ? { username, password, otp_token: otpToken } : { username, password })

    // Step 1 of two-step login for TOTP-enrolled accounts: password accepted,
    // no session issued yet. The caller prompts for the code and calls again.
    if (data?.requires_2fa) {
      return { status: 'otp_required', detail: data.detail }
    }
    if (!data?.user?.role || !data.user.username) {
      throw new Error('Unexpected login response from the server.')
    }

    // A new session starts with an empty cache: React Query keys are not
    // user-scoped, so anything cached before this point belongs to whoever
    // used this browser last.
    queryClient.clear()
    clearForeignDraft(data.user.username)
    // Server sets HttpOnly cookies; we keep only the non-PII render hints
    storeSessionUser(data.user)
    setUser(data.user)
    setIsLoading(false)
    if (data.requires_2fa_setup) {
      // Staff account without an authenticator: the backend still issues the
      // session, but sends the user to enrol.
      router.replace('/dashboard/two-factor')
    } else {
      router.replace(data.user.role === 'customer' ? '/apply' : '/dashboard')
    }
    return { status: 'ok' }
  }, [router, queryClient])

  const register = useCallback(async (formData: RegisterPayload) => {
    await authApi.getCsrfToken()
    await authApi.register(formData)
    await login(formData.username, formData.password)
  }, [login])

  const logout = useCallback(async () => {
    try {
      // POST to logout — server blacklists refresh token and clears cookies
      await api.post('/auth/logout/')
    } catch {
      // Logout even if the API call fails
    }
    // Session hints, the query cache and per-user local storage (drafts)
    resetClientState(queryClient)
    setUser(null)
    router.replace('/login')
  }, [router, queryClient])

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
