import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser, mockModelCard } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/dashboard/model-health',
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

import ModelHealthPage from '@/app/dashboard/model-health/page'

const mockMetrics = {
  id: 'm1',
  algorithm: 'xgb',
  version: '3',
  accuracy: 0.87,
  precision: 0.85,
  recall: 0.82,
  f1_score: 0.84,
  auc_roc: 0.91,
  brier_score: 0.12,
  optimal_threshold: 0.5,
  confusion_matrix: { tp: 1, fp: 1, tn: 1, fn: 1 },
  roc_curve_data: { fpr: [0, 1], tpr: [0, 1] },
  feature_importances: {},
  fairness_metrics: { gender: { disparate_impact_ratio: 0.92, passes_80_percent_rule: true } },
  calibration_data: { ece: 0.04, fraction_of_positives: [0.1, 0.5, 0.9], mean_predicted_value: [0.1, 0.5, 0.9] },
  threshold_analysis: {
    sweep: [{ threshold: 0.5, precision: 0.85, recall: 0.82, f1: 0.83, fpr: 0.1, approval_rate: 0.55 }],
    f1_optimal_threshold: 0.5,
    youden_j_threshold: 0.48,
    cost_optimal_threshold: 0.55,
  },
  is_active: true,
  decile_analysis: { deciles: [] },
}

function renderPage(role: 'admin' | 'officer' = 'admin') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider
        value={{
          user: { ...mockUser, role },
          isLoading: false,
          login: vi.fn(),
          register: vi.fn(),
          logout: vi.fn(),
        } as any}
      >
        <ModelHealthPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('ModelHealthPage', () => {
  beforeEach(() => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => HttpResponse.json(mockMetrics)),
      http.get(`${API_URL}/ml/models/active/model-card/`, () => HttpResponse.json({ model_card: mockModelCard })),
      http.get(`${API_URL}/ml/models/active/drift-reports/`, () => HttpResponse.json([]))
    )
  })

  it('renders the three tab triggers', async () => {
    renderPage()
    // Local Tabs renders <button> (not role="tab"), so query by button name
    await waitFor(() => expect(screen.getByRole('button', { name: /production status/i })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /model detail/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^governance$/i })).toBeInTheDocument()
  })

  it('Production Status is the default tab content', async () => {
    renderPage()
    // Calibration card rendered by the production status tab
    await waitFor(() => expect(screen.getAllByText(/calibration/i).length).toBeGreaterThan(0))
  })

  it('clicking Model Detail tab switches to that view', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: /model detail/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /model detail/i }))
    // <h3>XGBoost</h3> appears in the tab header; also rendered inside the
    // admin Select option list — disambiguate with heading role.
    await waitFor(() => expect(screen.getByRole('heading', { name: /XGBoost/i })).toBeInTheDocument())
  })

  it('clicking Governance tab switches to that view', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: /^governance$/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /^governance$/i }))
    await waitFor(() => expect(screen.getByRole('heading', { name: /intended use/i })).toBeInTheDocument())
  })
})
