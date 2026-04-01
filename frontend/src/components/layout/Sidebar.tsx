'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, FileText, BarChart3, Mail, Bot, UserCircle, Users, ShieldAlert, ClipboardList, ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth'
import { LogoIcon } from '@/components/ui/logo'

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/dashboard/applications', label: 'Applications', icon: FileText },
  { href: '/dashboard/human-review', label: 'Human Review', icon: ShieldAlert, staffOnly: true },
  { href: '/dashboard/customers', label: 'Customers', icon: Users, staffOnly: true },
  { href: '/dashboard/profile', label: 'My Profile', icon: UserCircle },
  { href: '/dashboard/model-metrics', label: 'Model Metrics', icon: BarChart3 },
  { href: '/dashboard/model-card', label: 'Model Card', icon: ShieldCheck, staffOnly: true },
  { href: '/dashboard/emails', label: 'Emails', icon: Mail },
  { href: '/dashboard/agents', label: 'Agent Workflows', icon: Bot },
  { href: '/dashboard/audit', label: 'Audit Log', icon: ClipboardList, staffOnly: true },
]

interface SidebarProps {
  isOpen: boolean
  onClose: () => void
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname()
  const { user } = useAuth()

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={onClose}
          onKeyDown={(e) => e.key === 'Escape' && onClose()}
          role="button"
          tabIndex={-1}
          aria-label="Close sidebar"
        />
      )}
      <aside
        aria-label="Main navigation"
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col gradient-sidebar text-white transition-transform duration-300 ease-in-out lg:static lg:translate-x-0 border-r border-white/[0.06]",
          isOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {/* Brand */}
        <div className="flex h-16 items-center gap-2.5 px-6">
          <LogoIcon />
          <span className="text-lg font-bold tracking-tight">AussieLoanAI</span>
        </div>

        {/* Navigation */}
        <nav className="min-h-0 flex-1 overflow-y-auto space-y-1 px-3 py-4">
          <p className="px-3 mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Menu
          </p>
          {navItems.filter((item) => !('staffOnly' in item && item.staffOnly) || (user?.role === 'admin' || user?.role === 'officer')).map((item) => {
            const isActive = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href))
            const linkClass = cn(
              "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200 outline-none focus-visible:outline-none focus:outline-none focus:ring-0 focus-visible:ring-0 active:bg-transparent",
              isActive
                ? "bg-gradient-to-r from-blue-500/20 to-indigo-500/15 text-white shadow-sm shadow-blue-500/10"
                : "text-slate-400 hover:text-white"
            )
            const content = (
              <>
                <item.icon className={cn("h-[18px] w-[18px]", isActive && "text-blue-400")} />
                {item.label}
                {isActive && (
                  <div className="ml-auto h-1.5 w-1.5 rounded-full bg-blue-400" />
                )}
              </>
            )
            if ('external' in item && item.external) {
              return (
                <a key={item.href} href={item.href} target="_blank" rel="noopener noreferrer" className={linkClass}>
                  {content}
                </a>
              )
            }
            return (
              <Link key={item.href} href={item.href} onClick={onClose} className={linkClass}>
                {content}
              </Link>
            )
          })}
        </nav>

        {/* User card */}
        {user && (
          <div className="border-t border-white/10 p-4">
            <div className="flex items-center gap-3 rounded-lg bg-white/5 p-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-blue-400 via-indigo-500 to-violet-500 text-sm font-semibold text-white shadow-lg shadow-indigo-500/30 border border-white/20">
                {user.first_name?.[0] || user.username[0].toUpperCase()}
              </div>
              <div className="flex-1 overflow-hidden">
                <p className="truncate text-sm font-medium text-white">
                  {user.first_name ? `${user.first_name} ${user.last_name}` : user.username}
                </p>
                <p className="text-xs text-slate-400 capitalize">{user.role}</p>
              </div>
            </div>
          </div>
        )}
      </aside>
    </>
  )
}
