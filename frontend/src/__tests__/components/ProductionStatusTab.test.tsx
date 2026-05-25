import { render, screen } from '@testing-library/react'
import { ProductionStatusTab } from '@/components/model-health/ProductionStatusTab'
import type { ModelMetrics, DriftReport } from '@/types'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

const baseMetrics: ModelMetrics = {
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
  fairness_metrics: {
    gender: { disparate_impact_ratio: 0.92, passes_80_percent_rule: true },
    state: { disparate_impact_ratio: 0.60, passes_80_percent_rule: false },
  },
  calibration_data: { ece: 0.04, fraction_of_positives: [0.1, 0.5, 0.9], mean_predicted_value: [0.1, 0.5, 0.9] },
  threshold_analysis: {
    sweep: [{ threshold: 0.5, precision: 0.85, recall: 0.82, f1: 0.83, fpr: 0.1, approval_rate: 0.55 }],
    f1_optimal_threshold: 0.51,
    youden_j_threshold: 0.48,
    cost_optimal_threshold: 0.55,
  },
  is_active: true,
} as unknown as ModelMetrics

const driftReports: DriftReport[] = [
  {
    id: 'r1',
    model_version: 'm1',
    report_date: '2026-05-24',
    period_start: '2026-05-17',
    period_end: '2026-05-24',
    num_predictions: 100,
    psi_score: 0.32,
    psi_per_feature: { credit_score: 0.35 },
    mean_probability: 0.4,
    std_probability: 0.15,
    approval_rate: 0.55,
    drift_detected: true,
    alert_level: 'significant',
    created_at: '2026-05-24T00:00:00Z',
  },
] as unknown as DriftReport[]

describe('ProductionStatusTab', () => {
  it('renders the alerts band when fairness fails and drift is significant', () => {
    render(<ProductionStatusTab metrics={baseMetrics} driftReports={driftReports} />)
    const alerts = screen.getByRole('region', { name: /alerts/i })
    expect(alerts).toBeInTheDocument()
    expect(alerts).toHaveTextContent(/fairness/i)
    expect(alerts).toHaveTextContent(/drift/i)
  })

  it('omits the alerts band when nothing breaches', () => {
    const passingMetrics: ModelMetrics = {
      ...baseMetrics,
      fairness_metrics: {
        gender: { disparate_impact_ratio: 0.92, passes_80_percent_rule: true },
      },
    } as unknown as ModelMetrics
    const cleanDrift: DriftReport[] = [
      { ...driftReports[0], psi_score: 0.05, alert_level: 'none', drift_detected: false } as unknown as DriftReport,
    ]
    render(<ProductionStatusTab metrics={passingMetrics} driftReports={cleanDrift} />)
    expect(screen.queryByRole('region', { name: /alerts/i })).not.toBeInTheDocument()
  })

  it('renders the four expected sections by name', () => {
    render(<ProductionStatusTab metrics={baseMetrics} driftReports={driftReports} />)
    // Drift Overview (existing component) — text contains "drift" (case-insensitive matches multiple)
    expect(screen.getAllByText(/drift/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/fairness/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/calibration/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/threshold/i).length).toBeGreaterThan(0)
  })
})
