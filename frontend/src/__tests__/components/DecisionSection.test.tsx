import { render, screen } from '@testing-library/react'
import { DecisionSection } from '@/components/applications/DecisionSection'
import { LoanDecision } from '@/types'

vi.mock('@/components/metrics/FeatureImportance', () => ({
  FeatureImportance: () => <div data-testid="feature-importance" />,
}))
vi.mock('@/components/metrics/ShapWaterfall', () => ({
  ShapWaterfall: () => <div data-testid="shap-waterfall" />,
}))
const baseDecision: LoanDecision = {
  id: 'dec-1',
  decision: 'approved',
  confidence: 0.873,
  risk_score: 0.42,
  feature_importances: { income: 0.35, credit_score: 0.28 },
  shap_values: { income: 0.12, credit_score: -0.05 },
  model_version: 'rf-v2.1',
  reasoning: 'Strong income-to-debt ratio with excellent credit history.',
  created_at: '2026-03-30T10:00:00Z',
}

function renderDecision(overrides: Partial<LoanDecision> = {}) {
  const decision = { ...baseDecision, ...overrides }
  return render(<DecisionSection decision={decision} />)
}

describe('DecisionSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders approved decision with green badge', () => {
    const { container } = renderDecision({ decision: 'approved' })
    const badge = container.querySelector('.bg-green-100')
    expect(badge).toBeInTheDocument()
    expect(screen.getByText('APPROVED')).toBeInTheDocument()
  })

  it('renders denied decision with red badge', () => {
    const { container } = renderDecision({ decision: 'denied' })
    const badge = container.querySelector('.bg-red-100')
    expect(badge).toBeInTheDocument()
    expect(screen.getByText('DENIED')).toBeInTheDocument()
  })

  it('shows model version', () => {
    renderDecision({ model_version: 'xgb-v3.0' })
    expect(screen.getByText('Model: xgb-v3.0')).toBeInTheDocument()
  })

  it('shows confidence percentage', () => {
    renderDecision({ confidence: 0.873 })
    expect(screen.getByText('Confidence: 87.3%')).toBeInTheDocument()
  })

  it('shows risk score when present', () => {
    renderDecision({ risk_score: 0.42 })
    expect(screen.getByText('Risk Score: 0.42')).toBeInTheDocument()
  })

  it('hides risk score when null', () => {
    renderDecision({ risk_score: null })
    expect(screen.queryByText(/Risk Score/)).not.toBeInTheDocument()
  })

  it('shows reasoning text', () => {
    renderDecision({ reasoning: 'Strong income-to-debt ratio with excellent credit history.' })
    expect(screen.getByText('Strong income-to-debt ratio with excellent credit history.')).toBeInTheDocument()
  })

  it('renders FeatureImportance when feature_importances has data (object)', () => {
    renderDecision({ feature_importances: { income: 0.35 } })
    expect(screen.getByTestId('feature-importance')).toBeInTheDocument()
  })

  it('renders FeatureImportance when feature_importances has data (array)', () => {
    renderDecision({
      feature_importances: [{ feature: 'income', importance: 0.35 }],
    })
    expect(screen.getByTestId('feature-importance')).toBeInTheDocument()
  })

  it('hides FeatureImportance when feature_importances is empty object', () => {
    renderDecision({ feature_importances: {} })
    expect(screen.queryByTestId('feature-importance')).not.toBeInTheDocument()
  })

  it('hides FeatureImportance when feature_importances is empty array', () => {
    renderDecision({ feature_importances: [] as any })
    expect(screen.queryByTestId('feature-importance')).not.toBeInTheDocument()
  })

  it('renders ShapWaterfall when shap_values has data', () => {
    renderDecision({ shap_values: { income: 0.12 } })
    expect(screen.getByTestId('shap-waterfall')).toBeInTheDocument()
  })

  it('hides ShapWaterfall when shap_values is missing', () => {
    renderDecision({ shap_values: undefined })
    expect(screen.queryByTestId('shap-waterfall')).not.toBeInTheDocument()
  })

  it('hides ShapWaterfall when shap_values is empty', () => {
    renderDecision({ shap_values: {} })
    expect(screen.queryByTestId('shap-waterfall')).not.toBeInTheDocument()
  })

})
