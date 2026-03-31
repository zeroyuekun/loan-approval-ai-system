import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DecisionSection } from '@/components/applications/DecisionSection'
import { LoanDecision } from '@/types'
import { loansApi } from '@/lib/api'

vi.mock('@/components/metrics/FeatureImportance', () => ({
  FeatureImportance: () => <div data-testid="feature-importance" />,
}))
vi.mock('@/components/metrics/ShapWaterfall', () => ({
  ShapWaterfall: () => <div data-testid="shap-waterfall" />,
}))
vi.mock('@/lib/api', () => ({
  loansApi: { downloadDecisionLetter: vi.fn() },
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

function renderDecision(overrides: Partial<LoanDecision> = {}, loanId = 'loan-123') {
  const decision = { ...baseDecision, ...overrides }
  return render(<DecisionSection decision={decision} loanId={loanId} />)
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

  it('download button triggers PDF download', async () => {
    const user = userEvent.setup()
    const mockBlob = new Blob(['pdf-content'], { type: 'application/pdf' })
    vi.mocked(loansApi.downloadDecisionLetter).mockResolvedValue({ data: mockBlob } as any)

    const createObjectURLMock = vi.fn(() => 'blob:http://localhost/fake-url')
    const revokeObjectURLMock = vi.fn()
    window.URL.createObjectURL = createObjectURLMock
    window.URL.revokeObjectURL = revokeObjectURLMock

    renderDecision({}, 'loan-456')

    const button = screen.getByText('Download Decision Letter')
    await user.click(button)

    await waitFor(() => {
      expect(loansApi.downloadDecisionLetter).toHaveBeenCalledWith('loan-456')
    })
    expect(createObjectURLMock).toHaveBeenCalled()
    expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:http://localhost/fake-url')
  })

  it('download button shows loading state while generating', async () => {
    const user = userEvent.setup()

    let resolveDownload!: (value: any) => void
    vi.mocked(loansApi.downloadDecisionLetter).mockImplementation(
      () => new Promise((resolve) => { resolveDownload = resolve })
    )

    renderDecision()

    const button = screen.getByText('Download Decision Letter')
    await user.click(button)

    await waitFor(() => {
      expect(screen.getByText('Generating...')).toBeInTheDocument()
    })

    // Resolve and verify it returns to normal
    resolveDownload({ data: new Blob(['pdf']) })

    await waitFor(() => {
      expect(screen.getByText('Download Decision Letter')).toBeInTheDocument()
    })
  })
})
