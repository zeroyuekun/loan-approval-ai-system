'use client'

import { useState } from 'react'
import { usePathname } from 'next/navigation'
import { Sidebar } from './Sidebar'
import { TopNav } from './TopNav'

const pageTitles: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/dashboard/applications': 'Loan Applications',
  '/dashboard/applications/new': 'New Application',
  '/dashboard/customers': 'Customers',
  '/dashboard/profile': 'My Profile',
  '/dashboard/model-metrics': 'Model Metrics',
  '/dashboard/emails': 'Generated Emails',
  '/dashboard/agents': 'Agent Workflows',
}

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const pathname = usePathname()

  const title = pageTitles[pathname] || (pathname.includes('/applications/') ? 'Application Detail' : 'Dashboard')

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopNav title={title} onMenuClick={() => setSidebarOpen(true)} />
        <main className="flex-1 overflow-y-auto p-4 lg:p-8">
          <div className="mx-auto max-w-7xl">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
