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
      localStorage.setItem('user', JSON.stringify(data))
      setRoleCookie(data.role)
    } catch {
      setUser(null)
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('user')
      clearRoleCookie()
    }
  }, [])

  // On mount, check localStorage for existing session
  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (token) {
      // Load cached user immediately to avoid flicker
      const cached = localStorage.getItem('user')
      if (cached) {
        try {
          const parsed = JSON.parse(cached)
          setUser(parsed)
          setRoleCookie(parsed.role)
        } catch {}
      }
      // Then verify with the server
      fetchProfile().finally(() => setIsLoading(false))
    } else {
      setIsLoading(false)
    }
  }, [fetchProfile])

  const login = useCallback(async (username: string, password: string) => {
    const { data } = await authApi.login({ username, password })
    localStorage.setItem('access_token', data.tokens.access)
    localStorage.setItem('refresh_token', data.tokens.refresh)
    localStorage.setItem('user', JSON.stringify(data.user))
    setUser(data.user)
    setRoleCookie(data.user.role)
    setIsLoading(false)
    router.replace(data.user.role === 'customer' ? '/apply' : '/dashboard')
  }, [router])

  const register = useCallback(async (formData: any) => {
    await authApi.register(formData)
    await login(formData.username, formData.password)
  }, [login])

  const logout = useCallback(() => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    clearRoleCookie()
    setUser(null)
    router.replace('/login')
  }, [router])

  // Auto log-off after 5 minutes of inactivity
  const IDLE_TIMEOUT_MS = 5 * 60 * 1000
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const resetIdleTimer = useCallback(() => {
    if (idleTimer.current) clearTimeout(idleTimer.current)
    if (localStorage.getItem('access_token')) {
      idleTimer.current = setTimeout(() => {
        logout()
      }, IDLE_TIMEOUT_MS)
    }
  }, [logout])

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
