'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth'
import { LogOut, FileText, UserCircle, ChevronDown } from 'lucide-react'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import { LogoIcon } from '@/components/ui/logo'
import Link from 'next/link'

export default function CustomerLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { user, isLoading, logout } = useAuth()
  const router = useRouter()
  const [showDropdown, setShowDropdown] = useState(false)

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace('/login')
    }
    if (!isLoading && user && user.role !== 'customer') {
      router.replace('/dashboard')
    }
  }, [user, isLoading, router])

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex items-center gap-3 text-muted-foreground">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-sm font-medium">Loading...</span>
        </div>
      </div>
    )
  }

  if (!user || user.role !== 'customer') return null

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b border-blue-700/30 gradient-primary backdrop-blur-xl shadow-lg shadow-blue-900/10">
        <div className="mx-auto flex h-16 max-w-4xl items-center justify-between px-4">
          <Link href="/apply" className="flex items-center gap-2.5">
            <LogoIcon />
            <span className="text-lg font-bold tracking-tight text-white">AussieLoanAI</span>
          </Link>
          <div className="flex items-center gap-4">
            <Link
              href="/apply"
              className="flex items-center gap-2 text-sm font-medium text-blue-200 hover:text-white transition-colors"
            >
              <FileText className="h-4 w-4" />
              <span className="hidden sm:inline">My Applications</span>
            </Link>
            <div className="h-5 w-px bg-blue-400/30" />
            <div className="relative">
              <button
                className="flex items-center gap-2 rounded-full bg-blue-800/40 px-3 py-1.5 text-sm font-medium text-blue-100 hover:bg-blue-800/60 transition-colors"
                onClick={() => setShowDropdown(!showDropdown)}
                aria-expanded={showDropdown}
                aria-haspopup="true"
              >
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-[11px] font-semibold text-white">
                  {user.first_name?.[0] || user.username?.[0]?.toUpperCase()}
                </div>
                <span className="hidden sm:inline">
                  {user.first_name ? `${user.first_name} ${user.last_name}` : user.username}
                </span>
                <ChevronDown className="h-3.5 w-3.5 text-blue-300" />
              </button>

              {showDropdown && (
                <>
                  <div className="fixed inset-0" onClick={() => setShowDropdown(false)} />
                  <div className="absolute right-0 top-full mt-2 w-56 rounded-xl border border-slate-200/60 bg-white p-1.5 shadow-lg animate-in fade-in slide-in-from-top-2 duration-200 z-50">
                    <div className="px-3 py-2.5">
                      <p className="text-sm font-medium text-foreground">{user.first_name} {user.last_name}</p>
                      <p className="text-xs text-muted-foreground">{user.email}</p>
                    </div>
                    <hr className="my-1" />
                    <Link
                      href="/apply/profile/edit"
                      className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-slate-100 transition-colors"
                      onClick={() => setShowDropdown(false)}
                    >
                      <UserCircle className="h-4 w-4" />
                      Edit Profile
                    </Link>
                    <button
                      className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
                      onClick={() => {
                        setShowDropdown(false)
                        logout()
                      }}
                    >
                      <LogOut className="h-4 w-4" />
                      Sign Out
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-8">
        <ErrorBoundary>
          {children}
        </ErrorBoundary>
      </main>
    </div>
  )
}
