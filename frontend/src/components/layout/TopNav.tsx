'use client'

import { useState } from 'react'
import { Menu, LogOut, User } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'

interface TopNavProps {
  title: string
  onMenuClick: () => void
}

export function TopNav({ title, onMenuClick }: TopNavProps) {
  const { user, logout } = useAuth()
  const [showDropdown, setShowDropdown] = useState(false)

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b bg-background px-4 lg:px-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" className="lg:hidden" onClick={onMenuClick}>
          <Menu className="h-5 w-5" />
        </Button>
        <h2 className="text-lg font-semibold">{title}</h2>
      </div>

      <div className="relative">
        <Button
          variant="ghost"
          size="sm"
          className="flex items-center gap-2"
          onClick={() => setShowDropdown(!showDropdown)}
        >
          <User className="h-4 w-4" />
          <span className="hidden sm:inline">{user?.username}</span>
        </Button>

        {showDropdown && (
          <>
            <div className="fixed inset-0" onClick={() => setShowDropdown(false)} />
            <div className="absolute right-0 top-full mt-1 w-48 rounded-md border bg-card p-1 shadow-md">
              <div className="px-3 py-2 text-sm text-muted-foreground">
                {user?.email}
              </div>
              <hr className="my-1" />
              <button
                className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent"
                onClick={() => {
                  setShowDropdown(false)
                  logout()
                }}
              >
                <LogOut className="h-4 w-4" />
                Logout
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  )
}
