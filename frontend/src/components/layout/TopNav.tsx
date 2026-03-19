'use client'

import { useState } from 'react'
import { Menu, LogOut, UserCircle, ChevronDown } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import Link from 'next/link'

interface TopNavProps {
  title: string
  onMenuClick: () => void
}

export function TopNav({ title, onMenuClick }: TopNavProps) {
  const { user, logout } = useAuth()
  const [showDropdown, setShowDropdown] = useState(false)

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-slate-200/60 bg-white/95 backdrop-blur-xl px-4 lg:px-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" className="lg:hidden" onClick={onMenuClick}>
          <Menu className="h-5 w-5" />
        </Button>
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      </div>

      <div className="relative">
        <button
          className="flex items-center gap-2 rounded-full border border-slate-200/60 bg-gradient-to-b from-white to-slate-50 px-3 py-1.5 text-sm font-medium shadow-soft transition-all hover:shadow-elevated"
          onClick={() => setShowDropdown(!showDropdown)}
          aria-expanded={showDropdown}
          aria-haspopup="true"
        >
          <div className="flex h-6 w-6 items-center justify-center rounded-full gradient-primary text-[11px] font-semibold text-white">
            {user?.first_name?.[0] || user?.username?.[0]?.toUpperCase()}
          </div>
          <span className="hidden sm:inline text-foreground">{user?.username}</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        </button>

        {showDropdown && (
          <>
            <div className="fixed inset-0" onClick={() => setShowDropdown(false)} />
            <div className="absolute right-0 top-full mt-2 w-52 rounded-xl border border-slate-200/60 bg-gradient-to-b from-white to-slate-50/90 p-1.5 shadow-elevated backdrop-blur-xl animate-in fade-in slide-in-from-top-2 duration-200">
              <div className="px-3 py-2.5">
                <p className="text-sm font-medium">{user?.first_name} {user?.last_name}</p>
                <p className="text-xs text-muted-foreground">{user?.email}</p>
              </div>
              <hr className="my-1" />
              <Link
                href="/dashboard/profile"
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
    </header>
  )
}
