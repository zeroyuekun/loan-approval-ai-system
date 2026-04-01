'use client'

import { useState } from 'react'
import { usePathname } from 'next/navigation'
import { Sidebar } from './Sidebar'
import { TopNav } from './TopNav'

const pageTitles: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/dashboard/applications': 'Loan Applications',
  '/dashboard/applications/new': 'New Application',
  '/dashboard/human-review': 'Human Review',
  '/dashboard/customers': 'Customers',
  '/dashboard/profile': 'My Profile',
  '/dashboard/model-metrics': 'Model Metrics',
  '/dashboard/model-card': 'Model Card',
  '/dashboard/emails': 'Generated Emails',
  '/dashboard/agents': 'Agent Workflows',
}

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const pathname = usePathname()

  const title = pageTitles[pathname] || (pathname.includes('/applications/') ? 'Application Detail' : 'Dashboard')

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-4 focus:left-4 focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground focus:shadow-lg"
      >
        Skip to main content
      </a>
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopNav title={title} onMenuClick={() => setSidebarOpen(true)} />
        <main id="main-content" className="flex-1 overflow-y-auto p-4 lg:p-8">
          <div>
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
