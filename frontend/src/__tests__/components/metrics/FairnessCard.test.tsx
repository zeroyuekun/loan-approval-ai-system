import { render, screen } from '@testing-library/react'
import { FairnessCard } from '@/components/metrics/FairnessCard'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

const metricsWithSmallGroup = {
  state: {
    groups: {
      nsw: { count: 500, actual_approval_rate: 0.6, predicted_approval_rate: 0.62, tpr: 0.8, fpr: 0.2, included_in_fairness: true },
      vic: { count: 450, actual_approval_rate: 0.58, predicted_approval_rate: 0.6, tpr: 0.78, fpr: 0.22, included_in_fairness: true },
      nt: { count: 12, actual_approval_rate: 0.3, predicted_approval_rate: 0.25, tpr: 0.5, fpr: 0.1, included_in_fairness: false },
    },
    disparate_impact_ratio: 0.97,
    equalized_odds_difference: 0.02,
    passes_80_percent_rule: true,
    min_group_size: 30,
    excluded_small_groups: ['nt'],
  },
}

describe('FairnessCard', () => {
  it('renders the per-attribute card with its Equalized Odds figure', () => {
    render(<FairnessCard fairnessMetrics={metricsWithSmallGroup} />)
    expect(screen.getByText('Fairness: State')).toBeInTheDocument()
    expect(screen.getByText(/Equalized Odds Diff: 0\.0200/)).toBeInTheDocument()
  })

  it('does not render a PASS/FAIL disparate-impact badge', () => {
    render(<FairnessCard fairnessMetrics={metricsWithSmallGroup} />)
    expect(screen.queryByText(/\bPASS\b/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\bFAIL\b/)).not.toBeInTheDocument()
    expect(screen.queryByText(/DI:/)).not.toBeInTheDocument()
  })

  it('notes small groups excluded from the ratio, with the threshold', () => {
    render(<FairnessCard fairnessMetrics={metricsWithSmallGroup} />)
    expect(screen.getByText(/excluded from the\s+disparate-impact ratio/i)).toBeInTheDocument()
    expect(screen.getByText(/fewer than 30 samples/i)).toBeInTheDocument()
    expect(screen.getByText(/1 small group/i)).toBeInTheDocument()
  })

  it('shows no exclusion note when every group is large enough', () => {
    const allLarge = {
      state: {
        ...metricsWithSmallGroup.state,
        groups: {
          nsw: { count: 500, actual_approval_rate: 0.6, predicted_approval_rate: 0.62, tpr: 0.8, fpr: 0.2, included_in_fairness: true },
          vic: { count: 450, actual_approval_rate: 0.58, predicted_approval_rate: 0.6, tpr: 0.78, fpr: 0.22, included_in_fairness: true },
        },
        excluded_small_groups: [],
      },
    }
    render(<FairnessCard fairnessMetrics={allLarge} />)
    expect(screen.queryByText(/excluded from the/i)).not.toBeInTheDocument()
  })

  it('hides the Equalized Odds figure (shows "—") when the ratio is null', () => {
    // Backend emits null DI / null pass when fewer than two groups are assessable.
    const notAssessable = {
      state: {
        groups: {
          nsw: { count: 500, actual_approval_rate: 0.6, predicted_approval_rate: 0.62, tpr: 0.8, fpr: 0.2, included_in_fairness: true },
          nt: { count: 12, actual_approval_rate: 0.3, predicted_approval_rate: 0.25, tpr: 0.5, fpr: 0.1, included_in_fairness: false },
        },
        disparate_impact_ratio: null,
        equalized_odds_difference: 0,
        passes_80_percent_rule: null,
        min_group_size: 30,
        excluded_small_groups: ['nt'],
      },
    }
    render(<FairnessCard fairnessMetrics={notAssessable} />)
    // Must NOT coerce an un-measurable result into a clean 0.0000.
    expect(screen.getByText(/Equalized Odds Diff: —/)).toBeInTheDocument()
    expect(screen.queryByText(/\bPASS\b/)).not.toBeInTheDocument()
  })

  it('renders nothing when there are no fairness metrics', () => {
    const { container } = render(<FairnessCard fairnessMetrics={{}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
