import { render, screen } from '@testing-library/react'
import { KpiStrip } from '@/components/metrics/KpiStrip'
import type { ModelMetrics, DriftReport } from '@/types'

function buildMetrics(overrides: Partial<ModelMetrics> = {}): ModelMetrics {
  return {
    id: 'model-1',
    algorithm: 'xgb',
    version: '1.0.0',
    accuracy: 0.84,
    precision: 0.82,
    recall: 0.81,
    f1_score: 0.815,
    auc_roc: 0.872,
    brier_score: 0.12,
    gini_coefficient: 0.74,
    ks_statistic: 0.55,
    log_loss: 0.4,
    ece: 0.018,
    optimal_threshold: 0.5,
    confusion_matrix: { tp: 100, fp: 20, tn: 110, fn: 30 },
    feature_importances: { credit_score: 0.21 },
    roc_curve_data: { fpr: [0, 1], tpr: [0, 1] },
    training_params: {},
    is_active: true,
    created_at: '2026-05-08T00:00:00Z',
    ...overrides,
  }
}

function buildDrift(overrides: Partial<DriftReport> = {}): DriftReport {
  return {
    id: 'drift-1',
    report_date: '2026-05-01',
    psi_score: 0.06,
    psi_per_feature: {},
    mean_probability: 0.45,
    std_probability: 0.2,
    approval_rate: 0.42,
    drift_detected: false,
    alert_level: 'none',
    num_predictions: 1000,
    period_start: '2026-04-24',
    period_end: '2026-04-30',
    ...overrides,
  }
}

describe('KpiStrip', () => {
  it('renders all four KPI tile labels', () => {
    render(<KpiStrip metrics={buildMetrics()} latestDrift={buildDrift()} />)
    expect(screen.getByText('AUC-ROC')).toBeInTheDocument()
    expect(screen.getByText('KS statistic')).toBeInTheDocument()
    expect(screen.getByText('PSI (latest)')).toBeInTheDocument()
    expect(screen.getByText('Approval rate')).toBeInTheDocument()
  })

  it('renders the AUC value to three decimal places', () => {
    render(<KpiStrip metrics={buildMetrics({ auc_roc: 0.872 })} />)
    expect(screen.getByText('0.872')).toBeInTheDocument()
  })

  it('renders an em-dash when AUC is missing', () => {
    render(<KpiStrip metrics={buildMetrics({ auc_roc: null })} />)
    // The dash appears at least once (AUC tile)
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1)
  })

  it('shows the regulator-floor reference for AUC and KS', () => {
    render(<KpiStrip metrics={buildMetrics()} />)
    expect(screen.getByText(/regulator floor: 0\.75/)).toBeInTheDocument()
    expect(screen.getByText(/regulator floor: 0\.30/)).toBeInTheDocument()
  })

  it('shows the PSI band thresholds', () => {
    render(<KpiStrip metrics={buildMetrics()} latestDrift={buildDrift()} />)
    expect(
      screen.getByText(/stable < 0\.10.*drift ≥ 0\.25/),
    ).toBeInTheDocument()
  })

  it('renders the latest drift PSI score', () => {
    render(
      <KpiStrip metrics={buildMetrics()} latestDrift={buildDrift({ psi_score: 0.083 })} />,
    )
    expect(screen.getByText('0.083')).toBeInTheDocument()
  })

  it('renders approval rate as a percentage', () => {
    render(
      <KpiStrip
        metrics={buildMetrics()}
        latestDrift={buildDrift({ approval_rate: 0.423 })}
      />,
    )
    expect(screen.getByText('42.3%')).toBeInTheDocument()
  })

  it('shows approval-rate delta vs previous period', () => {
    render(
      <KpiStrip
        metrics={buildMetrics()}
        latestDrift={buildDrift({ approval_rate: 0.43 })}
        previousDrift={buildDrift({ approval_rate: 0.4 })}
      />,
    )
    // 0.43 - 0.40 = 0.03 -> +3.0pp
    expect(screen.getByText(/\+3\.0pp vs prev/)).toBeInTheDocument()
  })

  it('falls back to "no prior period" when previousDrift is missing', () => {
    render(<KpiStrip metrics={buildMetrics()} latestDrift={buildDrift()} />)
    expect(screen.getByText(/no prior period/)).toBeInTheDocument()
  })

  it('falls back to em-dash for PSI/Approval when no drift report supplied', () => {
    render(<KpiStrip metrics={buildMetrics()} />)
    // Two em-dashes — PSI tile + Approval tile
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
  })

  it('exposes a region landmark for accessibility', () => {
    render(<KpiStrip metrics={buildMetrics()} latestDrift={buildDrift()} />)
    expect(
      screen.getByRole('region', { name: /model kpi summary/i }),
    ).toBeInTheDocument()
  })
})
