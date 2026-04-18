import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/dashboard',
  useSearchParams: () => new URLSearchParams(),
}))

// Recharts uses ResizeObserver which is not available in jsdom. Vitest 4's
// vi.fn() returns a spy that is not callable as a constructor, so use a
// class-based mock matching the ModelMetricsPage test pattern.
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverMock)

import DashboardPage from '@/app/dashboard/page'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={{ user: { ...mockUser, role: 'admin' as const }, isLoading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn() }}>
        <DashboardPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('DashboardPage', () => {
  it('shows loading skeletons initially', () => {
    server.use(
      http.get(`${API_URL}/loans/`, () => new Promise(() => {})),
      http.get(`${API_URL}/ml/model-versions/`, () => new Promise(() => {}))
    )
    renderPage()
    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
  })

  it('renders dashboard content when data loads', async () => {
    server.use(
      http.get(`${API_URL}/loans/`, () => HttpResponse.json({
        count: 1, next: null, previous: null,
        results: [{ id: 'l1', status: 'approved', applicant: mockUser, loan_amount: 25000, created_at: '2024-06-01T00:00:00Z', updated_at: '2024-06-01T00:00:00Z', decision: { decision: 'approved', confidence: 0.9, risk_score: 0.2, model_version: 'rf-v2.1', reasoning: 'Good', created_at: '2024-06-01T00:00:00Z' } }],
      })),
      http.get(`${API_URL}/ml/model-versions/`, () => HttpResponse.json([{ id: 1, algorithm: 'xgboost', version_label: 'v2.1', is_active: true, metrics: { accuracy: 0.87 }, created_at: '2024-01-01T00:00:00Z' }]))
    )
    renderPage()
    await waitFor(() => { expect(screen.getByText('1')).toBeInTheDocument() })
  })
})
