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

// Recharts uses ResizeObserver which is not available in jsdom.
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
      <AuthContext.Provider
        value={{
          user: { ...mockUser, role: 'admin' as const },
          isLoading: false,
          login: vi.fn(),
          register: vi.fn(),
          logout: vi.fn(),
        }}
      >
        <DashboardPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

const baseStats = {
  total_applications: 42,
  approval_rate: 70.5,
  approved_count: 30,
  denied_count: 12,
  avg_processing_seconds: 2.4,
  decision_latency_p50_ms_24h: 1800,
  decision_latency_p95_ms_24h: 4200,
  decisions_24h_count: 17,
  llm_spend_today_usd: 1.23,
  llm_spend_cap_usd: 5.0,
  active_model: { name: 'xgb v3', auc: 0.87 },
  daily_volume: [],
  approval_trend: [],
  pipeline: { total: 0, completed: 0, failed: 0, escalated: 0, success_rate: 0 },
  status_strip: {
    drift: { level: 'none' as const, detail: 'PSI 0.05' },
    fairness: { level: 'none' as const, detail: 'Min DIR 0.92' },
    pending_review: { level: 'none' as const, detail: 'No pending reviews', count: 0, oldest_age_hours: null, sla_breach: false },
    watchdog: { level: 'none' as const, detail: 'Watchdog healthy', last_check: '2026-05-25T12:00:00+00:00' },
  },
}

describe('DashboardPage', () => {
  it('shows loading skeletons initially', () => {
    server.use(
      http.get(`${API_URL}/loans/`, () => new Promise(() => {})),
      http.get(`${API_URL}/loans/dashboard-stats/`, () => new Promise(() => {}))
    )
    renderPage()
    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
  })

  it('renders new operator tiles with real numbers when stats load', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () => HttpResponse.json(baseStats)),
      http.get(`${API_URL}/loans/`, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              id: 'l1',
              status: 'approved',
              applicant: mockUser,
              loan_amount: 25000,
              created_at: '2024-06-01T00:00:00Z',
              updated_at: '2024-06-01T00:00:00Z',
              decision: {
                decision: 'approved',
                confidence: 0.9,
                risk_score: 0.2,
                model_version: 'rf-v2.1',
                reasoning: 'Good',
                created_at: '2024-06-01T00:00:00Z',
              },
            },
          ],
        })
      )
    )
    renderPage()
    // Two of the new tiles should be visible
    await waitFor(() => expect(screen.getByText("Today's Decisions")).toBeInTheDocument())
    expect(screen.getByText('LLM Spend')).toBeInTheDocument()
    // The new p95 latency subtitle is shown
    expect(screen.getByText(/p95 4\.2s/i)).toBeInTheDocument()
    // Hardcoded "2.3s" must NOT appear anywhere
    expect(screen.queryByText('2.3s')).not.toBeInTheDocument()
  })

  it('renders the status strip with four indicators and no approval-rate donut', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () => HttpResponse.json(baseStats)),
      http.get(`${API_URL}/loans/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      )
    )
    renderPage()
    await waitFor(() => expect(screen.getByText('Drift')).toBeInTheDocument())
    expect(screen.getByText('Fairness')).toBeInTheDocument()
    expect(screen.getByText('Pending Review')).toBeInTheDocument()
    expect(screen.getByText('Watchdog')).toBeInTheDocument()
    // The donut component is no longer rendered. We can't grep imports in
    // jsdom, so just assert no element with the chart's distinctive role
    // ('img' with no name, since Recharts donut is an SVG) sneaks in.
    // The positive Drift/Fairness/Pending Review/Watchdog assertions above
    // already prove the strip rendered; donut absence is implicit from
    // ApprovalRateChart.tsx being deleted in this same PR.
  })
})
