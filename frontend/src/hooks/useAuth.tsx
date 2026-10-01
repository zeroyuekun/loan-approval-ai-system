'use client'

import { useState, useEffect, useCallback, ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { AuthContext } from '@/lib/auth'
import api, { authApi, type RegisterPayload } from '@/lib/api'
import { clearSession, readSessionUser, setRoleCookie, storeSessionUser } from '@/lib/session'
import { User } from '@/types'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const router = useRouter()

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

  const login = useCallback(async (username: string, password: string) => {
    // Ensure we have a CSRF token before the login POST
    await authApi.getCsrfToken()
    const { data } = await authApi.login({ username, password })
    // Server sets HttpOnly cookies; we keep only the non-PII render hints
    storeSessionUser(data.user)
    setUser(data.user)
    setIsLoading(false)
    router.replace(data.user.role === 'customer' ? '/apply' : '/dashboard')
  }, [router])

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
    clearSession()
    setUser(null)
    router.replace('/login')
  }, [router])

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
