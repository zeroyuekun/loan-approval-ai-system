'use client'

import { useState, useEffect, useCallback, useRef, ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { AuthContext } from '@/lib/auth'
import { authApi } from '@/lib/api'
import { User } from '@/types'

function setRoleCookie(role: string) {
  const secure = window.location.hostname !== 'localhost' ? ';Secure' : ''
  document.cookie = `user_role=${role};path=/;max-age=${60 * 60 * 24 * 30};SameSite=Lax${secure}`
}

function clearRoleCookie() {
  document.cookie = 'user_role=;path=/;max-age=0'
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const router = useRouter()

  const fetchProfile = useCallback(async () => {
    try {
      const { data } = await authApi.getProfile()
      setUser(data)
      // Store non-sensitive user metadata for UI rendering (not tokens)
      sessionStorage.setItem('user', JSON.stringify(data))
      setRoleCookie(data.role)
      return true
    } catch {
      setUser(null)
      sessionStorage.removeItem('user')
      clearRoleCookie()
      return false
    }
  }, [])

  // On mount, try to restore session from HttpOnly cookies
  useEffect(() => {
    // Load cached user from sessionStorage for instant render
    const cached = sessionStorage.getItem('user')
    if (cached) {
      try {
        const parsed = JSON.parse(cached)
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
    // Server sets HttpOnly cookies — we only store user metadata
    sessionStorage.setItem('user', JSON.stringify(data.user))
    setUser(data.user)
    setRoleCookie(data.user.role)
    setIsLoading(false)
    router.replace(data.user.role === 'customer' ? '/apply' : '/dashboard')
  }, [router])

  const register = useCallback(async (formData: any) => {
    await authApi.getCsrfToken()
    await authApi.register(formData)
    await login(formData.username, formData.password)
  }, [login])

  const logout = useCallback(async () => {
    try {
      // POST to logout — server blacklists refresh token and clears cookies
      const api = (await import('@/lib/api')).default
      await api.post('/auth/logout/')
    } catch {
      // Logout even if the API call fails
    }
    sessionStorage.removeItem('user')
    clearRoleCookie()
    setUser(null)
    router.replace('/login')
  }, [router])

  // Auto log-off after 5 minutes of inactivity
  const IDLE_TIMEOUT_MS = 5 * 60 * 1000
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const resetIdleTimer = useCallback(() => {
    if (idleTimer.current) clearTimeout(idleTimer.current)
    if (user) {
      idleTimer.current = setTimeout(() => {
        logout()
      }, IDLE_TIMEOUT_MS)
    }
  }, [logout, user])

  useEffect(() => {
    if (!user) return

    const events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click']
    const handler = () => resetIdleTimer()

    events.forEach((e) => window.addEventListener(e, handler, { passive: true }))
    resetIdleTimer()

    return () => {
      events.forEach((e) => window.removeEventListener(e, handler))
      if (idleTimer.current) clearTimeout(idleTimer.current)
    }
  }, [user, resetIdleTimer])

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
