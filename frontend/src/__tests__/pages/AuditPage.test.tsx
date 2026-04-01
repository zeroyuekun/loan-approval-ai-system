import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/dashboard/audit',
  useSearchParams: () => new URLSearchParams(),
}))

import AuditPage from '@/app/dashboard/audit/page'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={{ user: { ...mockUser, role: 'admin' as const }, isLoading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn() }}>
        <AuditPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('AuditPage', () => {
  it('renders the page header and description', () => {
    server.use(http.get(`${API_URL}/loans/audit-logs/`, () => new Promise(() => {})))
    renderPage()
    expect(screen.getByText('Audit Log')).toBeInTheDocument()
    expect(screen.getByText('Track all system actions and changes')).toBeInTheDocument()
  })

  it('renders empty state when no entries', async () => {
    server.use(http.get(`${API_URL}/loans/audit-logs/`, () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })))
    renderPage()
    await waitFor(() => { expect(screen.getByText('No audit log entries found.')).toBeInTheDocument() })
  })

  it('renders filter controls', () => {
    server.use(http.get(`${API_URL}/loans/audit-logs/`, () => new Promise(() => {})))
    renderPage()
    expect(screen.getByPlaceholderText('Search by resource ID...')).toBeInTheDocument()
  })
})
