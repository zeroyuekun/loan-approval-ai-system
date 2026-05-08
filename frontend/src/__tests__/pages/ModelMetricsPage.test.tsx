import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser } from '@/test/mocks/handlers'
import { User, ModelMetrics } from '@/types'

const API_URL = 'http://localhost:8000/api/v1'

// Recharts uses ResizeObserver which is not available in jsdom
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/dashboard/model-metrics',
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}))

import ModelMetricsPage from '@/app/dashboard/model-metrics/page'

const mockMetrics: ModelMetrics = {
  id: 'model-1',
  algorithm: 'xgb',
  version: '3',
  accuracy: 0.87,
  precision: 0.85,
  recall: 0.82,
  f1_score: 0.835,
  auc_roc: 0.91,
  brier_score: 0.12,
  gini_coefficient: 0.82,
  ks_statistic: 0.65,
  optimal_threshold: 0.5,
  confusion_matrix: {
    tp: 850,
    fp: 150,
    tn: 870,
    fn: 130,
  },
  feature_importances: { credit_score: 0.25, income: 0.2 },
  roc_curve_data: { fpr: [0, 0.1, 1], tpr: [0, 0.9, 1] },
  training_params: {},
  is_active: true,
  created_at: '2024-06-01T00:00:00Z',
}

function renderPage(user: User = { ...mockUser, role: 'admin' as const }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={{
        user,
        isLoading: false,
        login: vi.fn(),
        register: vi.fn(),
        logout: vi.fn(),
      }}>
        <ModelMetricsPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('ModelMetricsPage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders header + KPI strip when an active model exists', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => {
        return HttpResponse.json(mockMetrics)
      }),
    )

    renderPage()

    // Header — algorithm name, version, Active badge
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'XGBoost' })).toBeInTheDocument()
    })
    expect(screen.getByText('v3')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()

    // KPI strip — lender headline tiles
    expect(
      screen.getByRole('region', { name: /model kpi summary/i }),
    ).toBeInTheDocument()
    expect(screen.getByText('0.910')).toBeInTheDocument()
    expect(screen.getByText('0.650')).toBeInTheDocument()
  })

  it('shows "no model" state when metrics returns 404', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => {
        return HttpResponse.json({ error: 'Not found' }, { status: 404 })
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('No active model found')).toBeInTheDocument()
    })
    // Admin should see train button
    expect(screen.getByRole('button', { name: /train model/i })).toBeInTheDocument()
  })

  it('train button triggers training mutation', async () => {
    let trainCalled = false
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => {
        return HttpResponse.json(mockMetrics)
      }),
      http.post(`${API_URL}/ml/models/train/`, () => {
        trainCalled = true
        return HttpResponse.json({ task_id: 'task-123', algorithm: 'xgb' })
      }),
      http.get(`${API_URL}/tasks/:taskId/status/`, () => {
        return HttpResponse.json({ task_id: 'task-123', status: 'STARTED', result: null, date_done: null })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'XGBoost' })).toBeInTheDocument()
    })

    const trainButton = screen.getByRole('button', { name: /train new model/i })
    await user.click(trainButton)

    await waitFor(() => {
      expect(trainCalled).toBe(true)
    })
  })

  it('shows training banner during training', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => {
        return HttpResponse.json(mockMetrics)
      }),
      http.post(`${API_URL}/ml/models/train/`, () => {
        return HttpResponse.json({ task_id: 'task-123', algorithm: 'xgb' })
      }),
      http.get(`${API_URL}/tasks/:taskId/status/`, () => {
        return HttpResponse.json({ task_id: 'task-123', status: 'STARTED', result: null, date_done: null })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'XGBoost' })).toBeInTheDocument()
    })

    const trainButton = screen.getByRole('button', { name: /train new model/i })
    await user.click(trainButton)

    // Banner copy is unique to the training-in-progress state — no duplicate
    // "Training" matches like the legacy test triggered.
    await waitFor(() => {
      expect(
        screen.getByText(/Running Optuna Bayesian optimization/i),
      ).toBeInTheDocument()
    })
  })

  it('shows error state on API failure', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => {
        return HttpResponse.json({ error: 'Server error' }, { status: 500 })
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Failed to load model metrics')).toBeInTheDocument()
    })
  })
})
