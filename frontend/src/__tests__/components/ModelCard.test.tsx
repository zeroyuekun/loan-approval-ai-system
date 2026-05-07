import { render, screen } from '@testing-library/react'
import { ModelCard } from '@/components/metrics/ModelCard'
import type { ModelMetrics } from '@/types'

/**
 * Build a fully-formed ModelMetrics payload with sensible defaults so each
 * test only has to override the field it cares about. Mirrors the shape the
 * `useModelMetrics` query returns from `/api/v1/ml/metrics/`.
 */
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
    feature_importances: {
      credit_score: 0.21,
      debt_to_income: 0.18,
      annual_income: 0.14,
      employment_length: 0.09,
      loan_amount: 0.08,
    },
    roc_curve_data: { fpr: [0, 1], tpr: [0, 1], thresholds: [], auc: 0.87 },
    training_params: {},
    calibration_data: {
      fraction_of_positives: [0.1, 0.5, 0.9],
      mean_predicted_value: [0.1, 0.5, 0.9],
      ece: 0.018,
      n_bins: 10,
    },
    fairness_metrics: {
      gender: { passes_80_percent_rule: true, disparate_impact_ratio: 0.93 },
      age_group: { passes_80_percent_rule: true, disparate_impact_ratio: 0.88 },
    },
    training_metadata: {
      training_segment: 'AU PAYG',
      psi_by_feature: { credit_score: 0.04, debt_to_income: 0.06 },
      overfitting_gap: 0.022,
      baseline_auc: 0.81,
      xgb_lift_over_baseline: 0.062,
    },
    is_active: true,
    created_at: '2026-05-07T00:00:00Z',
    ...overrides,
  }
}

describe('ModelCard', () => {
  it('renders the model card title', () => {
    render(<ModelCard metrics={buildMetrics()} />)
    expect(
      screen.getByRole('heading', { name: /model card/i }),
    ).toBeInTheDocument()
  })

  describe('segment sub-title', () => {
    it('shows the training_segment from training_metadata', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      expect(screen.getByText(/AU PAYG/)).toBeInTheDocument()
    })

    it('shows the algorithm + version next to the segment', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      // XGBoost label, not raw "xgb"
      expect(screen.getByText(/XGBoost/)).toBeInTheDocument()
      expect(screen.getByText(/v1\.0\.0/)).toBeInTheDocument()
    })

    it('falls back to "segment unspecified" when training_segment missing', () => {
      const m = buildMetrics({ training_metadata: { psi_by_feature: {} } })
      render(<ModelCard metrics={m} />)
      expect(screen.getByText(/segment unspecified/i)).toBeInTheDocument()
    })
  })

  describe('Performance section', () => {
    it('renders the Performance heading', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      expect(
        screen.getByRole('heading', { name: /performance/i }),
      ).toBeInTheDocument()
    })

    it('shows AUC with regulator-floor framing when above floor', () => {
      render(<ModelCard metrics={buildMetrics({ auc_roc: 0.872 })} />)
      // Section value uses .toFixed(3) for the AUC number itself
      expect(screen.getByText('0.872')).toBeInTheDocument()
      expect(
        screen.getByText(/above 0\.75 regulator floor/i),
      ).toBeInTheDocument()
    })

    it('flags AUC below floor as below', () => {
      render(<ModelCard metrics={buildMetrics({ auc_roc: 0.71 })} />)
      expect(
        screen.getByText(/below 0\.75 regulator floor/i),
      ).toBeInTheDocument()
    })

    it('shows the GMSC external benchmark next to AUC', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      // GMSC_AUC = 0.866
      expect(screen.getByText(/0\.866/)).toBeInTheDocument()
      expect(
        screen.getByText(/Give Me Some Credit/i),
      ).toBeInTheDocument()
    })
  })
})
