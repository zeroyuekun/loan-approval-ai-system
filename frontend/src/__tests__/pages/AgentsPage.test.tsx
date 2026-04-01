import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/dashboard/agents',
  useSearchParams: () => new URLSearchParams(),
}))

import AgentsPage from '@/app/dashboard/agents/page'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={{ user: { ...mockUser, role: 'admin' as const }, isLoading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn() }}>
        <AgentsPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('AgentsPage', () => {
  it('shows loading skeletons initially', () => {
    server.use(http.get(`${API_URL}/agents/runs/`, () => new Promise(() => {})))
    renderPage()
    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
  })

  it('shows empty state when no runs', async () => {
    server.use(http.get(`${API_URL}/agents/runs/`, () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })))
    renderPage()
    await waitFor(() => { expect(screen.getByText('No agent workflows yet')).toBeInTheDocument() })
  })

  it('renders grouped customer data', async () => {
    server.use(http.get(`${API_URL}/agents/runs/`, () => HttpResponse.json({
      count: 1, next: null, previous: null,
      results: [{ id: 'run-1', applicant_id: 1, applicant_name: 'Alice Smith', status: 'completed', steps: [], total_time_ms: 1000, error: '', created_at: '2024-06-01T00:00:00Z', updated_at: '2024-06-01T00:00:00Z', bias_reports: [], next_best_offers: [], marketing_emails: [] }],
    })))
    renderPage()
    await waitFor(() => { expect(screen.getByText('Alice Smith')).toBeInTheDocument() })
  })
})
