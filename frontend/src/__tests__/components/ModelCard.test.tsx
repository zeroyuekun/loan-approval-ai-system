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

    it('shows AUC alongside the regulator-floor reference', () => {
      render(<ModelCard metrics={buildMetrics({ auc_roc: 0.872 })} />)
      // Section value uses .toFixed(3) for the AUC number itself
      expect(screen.getByText('0.872')).toBeInTheDocument()
      // Neutral framing — no above/below verdict, just the reference threshold
      expect(
        screen.getByText(/regulator floor: 0\.75/i),
      ).toBeInTheDocument()
    })

    it('shows the same regulator-floor reference regardless of whether AUC clears it', () => {
      render(<ModelCard metrics={buildMetrics({ auc_roc: 0.71 })} />)
      // The AUC value renders, but the context line stays neutral — no
      // pass/fail framing because the training data is synthetic.
      expect(screen.getByText('0.710')).toBeInTheDocument()
      expect(
        screen.getByText(/regulator floor: 0\.75/i),
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

  describe('Credibility evidence section', () => {
    it('renders the Credibility heading', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      expect(
        screen.getByRole('heading', { name: /credibility/i }),
      ).toBeInTheDocument()
    })

    it('shows the top driver feature with its importance', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      // credit_score 0.21 is the largest in the fixture
      expect(screen.getByText(/credit_score/)).toBeInTheDocument()
      expect(screen.getByText(/0\.21/)).toBeInTheDocument()
    })

    it('lists the top 3 drivers in descending importance order', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      // top 3 from fixture: credit_score 0.21, debt_to_income 0.18, annual_income 0.14
      expect(screen.getByText(/credit_score/)).toBeInTheDocument()
      expect(screen.getByText(/debt_to_income/)).toBeInTheDocument()
      expect(screen.getByText(/annual_income/)).toBeInTheDocument()
      // employment_length 0.09 should NOT make the top-3 cut
      expect(screen.queryByText(/employment_length/)).not.toBeInTheDocument()
    })

    it('handles array-form feature_importances', () => {
      const m = buildMetrics({
        feature_importances: [
          { feature: 'foo', importance: 0.3 },
          { feature: 'bar', importance: 0.2 },
          { feature: 'baz', importance: 0.1 },
          { feature: 'qux', importance: 0.05 },
        ],
      })
      render(<ModelCard metrics={m} />)
      expect(screen.getByText(/foo/)).toBeInTheDocument()
      expect(screen.getByText(/bar/)).toBeInTheDocument()
      expect(screen.getByText(/baz/)).toBeInTheDocument()
      expect(screen.queryByText(/qux/)).not.toBeInTheDocument()
    })
  })

  describe('Trained-On section', () => {
    it('renders the Trained on heading', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      expect(
        screen.getByRole('heading', { name: /trained on/i }),
      ).toBeInTheDocument()
    })

    it('lists the AU calibration source short names', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      // From AU_CALIBRATION_SOURCES — at minimum ABS / APRA / RBA must appear
      expect(screen.getByText(/ABS/)).toBeInTheDocument()
      expect(screen.getByText(/APRA/)).toBeInTheDocument()
      expect(screen.getByText(/RBA/)).toBeInTheDocument()
    })

    it('exposes a "View calibration sources" link to the GitHub manifest', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      const link = screen.getByRole('link', {
        name: /view calibration sources/i,
      })
      expect(link).toHaveAttribute(
        'href',
        'https://github.com/zeroyuekun/loan-approval-ai-system/blob/master/backend/docs/CALIBRATION_SOURCES.md',
      )
    })
  })

  describe('Not-validated-for section', () => {
    it('renders the Not validated for heading', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      expect(
        screen.getByRole('heading', { name: /not validated for/i }),
      ).toBeInTheDocument()
    })

    it('lists the out-of-scope segments', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      // From NOT_VALIDATED_FOR — at least the commercial + non-AU items
      expect(screen.getByText(/Commercial \/ business lending/i)).toBeInTheDocument()
      expect(screen.getByText(/outside Australia/i)).toBeInTheDocument()
    })
  })

  describe('Production posture section', () => {
    it('renders the Production posture heading', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      expect(
        screen.getByRole('heading', { name: /production posture/i }),
      ).toBeInTheDocument()
    })

    it('shows Active when is_active=true', () => {
      render(<ModelCard metrics={buildMetrics({ is_active: true })} />)
      // The badge text appears in the posture section. Use the role-aware
      // matcher to avoid clashing with other "Active" copy elsewhere.
      const posture = screen.getByText(
        /serving live predictions on \/dashboard\/applications/i,
      )
      expect(posture).toBeInTheDocument()
    })

    it('shows Retired when is_active=false', () => {
      render(<ModelCard metrics={buildMetrics({ is_active: false })} />)
      expect(
        screen.getByText(/not currently serving predictions/i),
      ).toBeInTheDocument()
    })
  })

  describe('Empty-state banner', () => {
    it('renders an explanatory banner when AUC, ECE, and feature_importances are all missing', () => {
      const m = buildMetrics({
        auc_roc: null,
        ks_statistic: null,
        ece: null,
        calibration_data: null,
        feature_importances: {},
      })
      render(<ModelCard metrics={m} />)
      expect(
        screen.getByText(/limited evidence available/i),
      ).toBeInTheDocument()
      expect(
        screen.getByText(/re-train.*latest trainer/i),
      ).toBeInTheDocument()
    })
  })

  describe('Migrated rows from ModelHealthCard', () => {
    it('shows the train→test gap row when overfitting_gap is recorded', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      expect(screen.getByText(/Train→test gap/i)).toBeInTheDocument()
      // overfitting_gap = 0.022 in fixture
      expect(screen.getByText('0.022')).toBeInTheDocument()
      expect(
        screen.getByText(/industry ceiling: 0\.05/i),
      ).toBeInTheDocument()
    })

    it('shows lift over LR when baseline_auc + xgb_lift_over_baseline are recorded', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      expect(screen.getByText(/Lift over LR/i)).toBeInTheDocument()
      // xgb_lift_over_baseline = 0.062 in fixture (positive → "+0.062 AUC")
      expect(screen.getByText(/\+0\.062 AUC/)).toBeInTheDocument()
      // baseline_auc = 0.81 in fixture
      expect(screen.getByText(/vs LR baseline AUC 0\.810/i)).toBeInTheDocument()
    })

    it('omits gap and lift rows when their training_metadata fields are missing', () => {
      const m = buildMetrics({
        training_metadata: { training_segment: 'AU PAYG' },
      })
      render(<ModelCard metrics={m} />)
      expect(screen.queryByText(/Train→test gap/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/Lift over LR/i)).not.toBeInTheDocument()
    })
  })

  describe('Confusion row (replaces ConfusionMatrix card)', () => {
    it('shows precision, recall, and sample count derived from confusion_matrix', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      // tp=100, fp=20, tn=110, fn=30 → P 100/120 = 0.83, R 100/130 = 0.77, n 260
      expect(screen.getByText(/Confusion/i)).toBeInTheDocument()
      expect(screen.getByText(/P 0\.83 · R 0\.77/)).toBeInTheDocument()
      expect(screen.getByText(/n = 260/)).toBeInTheDocument()
    })

    it('skips the row when confusion_matrix is empty (n=0)', () => {
      const m = buildMetrics({
        confusion_matrix: { tp: 0, fp: 0, tn: 0, fn: 0 },
      })
      render(<ModelCard metrics={m} />)
      expect(screen.queryByText(/^Confusion$/)).not.toBeInTheDocument()
    })
  })

  describe('Decision thresholds section', () => {
    it('shows the active threshold when only optimal_threshold is set', () => {
      const m = buildMetrics({ optimal_threshold: 0.55, threshold_analysis: null })
      render(<ModelCard metrics={m} />)
      expect(
        screen.getByRole('heading', { name: /decision thresholds/i }),
      ).toBeInTheDocument()
      expect(screen.getByText('0.55')).toBeInTheDocument()
    })

    it('shows F1, Youden, and Cost-optimal thresholds from threshold_analysis', () => {
      const m = buildMetrics({
        optimal_threshold: 0.5,
        threshold_analysis: {
          sweep: [],
          f1_optimal_threshold: 0.47,
          youden_j_threshold: 0.49,
          cost_optimal_threshold: 0.52,
        },
      })
      render(<ModelCard metrics={m} />)
      expect(screen.getByText(/F1-optimal/i)).toBeInTheDocument()
      expect(screen.getByText('0.47')).toBeInTheDocument()
      expect(screen.getByText(/Youden's J/i)).toBeInTheDocument()
      expect(screen.getByText('0.49')).toBeInTheDocument()
      expect(screen.getByText(/Cost-optimal/i)).toBeInTheDocument()
      expect(screen.getByText('0.52')).toBeInTheDocument()
    })

    it('hides the section entirely when no threshold data is recorded', () => {
      const m = buildMetrics({
        optimal_threshold: null,
        threshold_analysis: null,
      })
      render(<ModelCard metrics={m} />)
      expect(
        screen.queryByRole('heading', { name: /decision thresholds/i }),
      ).not.toBeInTheDocument()
    })
  })

  describe('Show all features toggle', () => {
    it('shows a "Show all features" button when more than 3 features exist', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      // Fixture has 5 features → 2 hidden → toggle visible
      expect(
        screen.getByRole('button', { name: /show all features/i }),
      ).toBeInTheDocument()
    })

    it('does not render the toggle when only top-3 features exist', () => {
      const m = buildMetrics({
        feature_importances: {
          credit_score: 0.3,
          debt_to_income: 0.2,
          annual_income: 0.1,
        },
      })
      render(<ModelCard metrics={m} />)
      expect(
        screen.queryByRole('button', { name: /show all features/i }),
      ).not.toBeInTheDocument()
    })
  })

  describe('Raw training metadata footer', () => {
    it('renders a collapsed "Show raw training metadata" toggle', () => {
      render(<ModelCard metrics={buildMetrics()} />)
      expect(
        screen.getByRole('button', { name: /show raw training metadata/i }),
      ).toBeInTheDocument()
    })

    it('hides the footer when no metadata and no optimal_threshold are recorded', () => {
      const m = buildMetrics({
        training_metadata: null,
        optimal_threshold: null,
      })
      render(<ModelCard metrics={m} />)
      expect(
        screen.queryByRole('button', { name: /show raw training metadata/i }),
      ).not.toBeInTheDocument()
    })
  })
})
