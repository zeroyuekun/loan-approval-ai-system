import { render, screen } from '@testing-library/react'
import { ModelDetailTab } from '@/components/model-health/ModelDetailTab'
import { AuthContext } from '@/lib/auth'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ModelMetrics } from '@/types'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

const metrics: ModelMetrics = {
  id: 'm1',
  algorithm: 'xgb',
  version: '3',
  accuracy: 0.87,
  precision: 0.85,
  recall: 0.82,
  f1_score: 0.84,
  auc_roc: 0.91,
  gini_coefficient: 0.82,
  ks_statistic: 0.65,
  brier_score: 0.12,
  optimal_threshold: 0.5,
  confusion_matrix: { tp: 850, fp: 150, tn: 870, fn: 130 },
  roc_curve_data: { fpr: [0, 0.5, 1], tpr: [0, 0.8, 1] },
  feature_importances: { credit_score: 0.45, debt_to_income: 0.28 },
  decile_analysis: { deciles: [{ decile: 1, bad_rate: 0.4 }] },
  training_metadata: { num_features: 71 },
  is_active: true,
} as unknown as ModelMetrics

function wrap(ui: React.ReactElement, role: 'admin' | 'officer' = 'officer') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider
        value={{
          user: { id: 1, username: 'u', email: 'u@t.test', first_name: 'U', last_name: 'T', role },
          isLoading: false,
          login: () => {},
          register: () => {},
          logout: () => {},
        } as any}
      >
        {ui}
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('ModelDetailTab', () => {
  it('renders algorithm + version in the summary', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />)
    expect(screen.getByText(/XGBoost/i)).toBeInTheDocument()
    expect(screen.getByText(/v3/)).toBeInTheDocument()
  })

  it('renders all 8 metric tile labels when data is present', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />)
    for (const label of ['Accuracy', 'Precision', 'Recall', 'F1 Score', 'AUC-ROC', 'Gini', 'KS Statistic', 'Brier Score']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows Train New Model button for admin role', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />, 'admin')
    expect(screen.getByRole('button', { name: /train new model/i })).toBeInTheDocument()
  })

  it('hides Train New Model button for officer role', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />, 'officer')
    expect(screen.queryByRole('button', { name: /train new model/i })).not.toBeInTheDocument()
  })

  it('renders the Diagnostics accordion trigger', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />)
    expect(screen.getByText(/diagnostics/i)).toBeInTheDocument()
  })
})
