import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApplicationDetail } from '@/components/applications/ApplicationDetail'
import { LoanApplication, GeneratedEmail, AgentRun } from '@/types'

// Mock the pipeline orchestration hook
const mockHandleOrchestrate = vi.fn()
vi.mock('@/hooks/usePipelineOrchestration', () => ({
  usePipelineOrchestration: () => ({
    agentRun: null,
    orchestrating: false,
    pipelineQueued: false,
    pipelineError: null,
    pipelineDisabled: false,
    handleOrchestrate: mockHandleOrchestrate,
  }),
}))

// Mock child components that have their own complex dependencies
vi.mock('@/components/agents/WorkflowTimeline', () => ({
  WorkflowTimeline: ({ steps }: any) => <div data-testid="workflow-timeline">{steps.length} steps</div>,
}))
vi.mock('@/components/agents/NextBestOfferCard', () => ({
  NextBestOfferCard: ({ offer }: any) => <div data-testid="nbo-card">{offer.analysis}</div>,
}))
vi.mock('@/components/agents/MarketingEmailCard', () => ({
  MarketingEmailCard: ({ email }: any) => <div data-testid="marketing-email">{email.subject}</div>,
}))
vi.mock('@/components/emails/EmailPreview', () => ({
  EmailPreview: ({ email }: any) => <div data-testid="email-preview">{email.subject}</div>,
}))
vi.mock('@/components/emails/BiasScoreBadge', () => ({
  BiasScoreBadge: ({ score }: any) => <div data-testid="bias-badge">{score}</div>,
}))
vi.mock('@/components/metrics/FeatureImportance', () => ({
  FeatureImportance: () => <div data-testid="feature-importance">Feature chart</div>,
}))

const mockApplication: LoanApplication = {
  id: 'loan-123',
  applicant: {
    id: 1,
    username: 'jdoe',
    email: 'jdoe@example.com',
    role: 'customer',
    first_name: 'John',
    last_name: 'Doe',
  },
  annual_income: 85000,
  credit_score: 720,
  loan_amount: 25000,
  loan_term_months: 36,
  debt_to_income: 0.35,
  employment_length: 5,
  purpose: 'personal',
  home_ownership: 'rent',
  has_cosigner: false,
  property_value: null,
  deposit_amount: null,
  monthly_expenses: 3200,
  existing_credit_card_limit: 10000,
  number_of_dependants: 1,
  employment_type: 'payg_permanent',
  applicant_type: 'single',
  has_hecs: false,
  has_bankruptcy: false,
  status: 'pending',
  notes: 'Test application notes',
  created_at: '2025-01-15T10:00:00Z',
  updated_at: '2025-01-15T10:00:00Z',
  decision: {
    id: 'dec-1',
    decision: 'approved',
    confidence: 0.87,
    risk_score: 0.23,
    feature_importances: { credit_score: 0.35, income: 0.25 },
    model_version: 'xgboost-v2',
    reasoning: 'Strong credit profile with stable income.',
    created_at: '2025-01-15T10:01:00Z',
  },
}

const mockEmail: GeneratedEmail = {
  id: 'email-1',
  application_id: 'loan-123',
  decision: 'approved',
  subject: 'Your Loan Application Has Been Approved',
  body: 'Dear John, we are pleased to inform you...',
  model_used: 'claude-sonnet-4-20250514',
  passed_guardrails: true,
  attempt_number: 1,
  generation_time_ms: 1200,
  created_at: '2025-01-15T10:02:00Z',
  guardrail_checks: [],
}

function renderComponent(props: Partial<React.ComponentProps<typeof ApplicationDetail>> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ApplicationDetail
        application={mockApplication}
        {...props}
      />
    </QueryClientProvider>
  )
}

describe('ApplicationDetail', () => {
  beforeEach(() => {
    mockHandleOrchestrate.mockReset()
  })

  it('renders loading skeleton when isLoading is true', () => {
    renderComponent({ isLoading: true })
    // Skeleton elements should be present (no application data)
    expect(screen.queryByText('Application Information')).not.toBeInTheDocument()
  })

  it('renders application header with applicant name', () => {
    renderComponent()
    expect(screen.getByText('Application Information')).toBeInTheDocument()
    expect(screen.getByText('John Doe')).toBeInTheDocument()
  })

  it('renders financial details card', () => {
    renderComponent()
    expect(screen.getByText('Financial Details')).toBeInTheDocument()
    expect(screen.getByText('36 months')).toBeInTheDocument()
  })

  it('renders ML decision when present', () => {
    renderComponent()
    expect(screen.getByText('ML Decision')).toBeInTheDocument()
    expect(screen.getByText('APPROVED')).toBeInTheDocument()
    expect(screen.getByText('Strong credit profile with stable income.')).toBeInTheDocument()
  })

  it('renders email preview when email prop is provided', () => {
    renderComponent({ email: mockEmail })
    expect(screen.getByTestId('email-preview')).toBeInTheDocument()
  })

  it('does not render email preview when no email', () => {
    renderComponent()
    expect(screen.queryByTestId('email-preview')).not.toBeInTheDocument()
  })

  it('renders notes when present', () => {
    renderComponent()
    expect(screen.getByText('Notes')).toBeInTheDocument()
    expect(screen.getByText('Test application notes')).toBeInTheDocument()
  })

  it('renders Run AI Pipeline button for pending applications', () => {
    renderComponent()
    expect(screen.getByText('Run AI Pipeline')).toBeInTheDocument()
  })

  it('renders Re-run AI Pipeline button for non-pending applications', () => {
    renderComponent({
      application: { ...mockApplication, status: 'approved' },
    })
    expect(screen.getByText('Re-run AI Pipeline')).toBeInTheDocument()
  })

  it('calls handleOrchestrate when pipeline button is clicked', async () => {
    const user = userEvent.setup()
    renderComponent()

    await user.click(screen.getByText('Run AI Pipeline'))
    expect(mockHandleOrchestrate).toHaveBeenCalledTimes(1)
  })

  it('renders delete button when onDelete is provided', () => {
    renderComponent({ onDelete: vi.fn() })
    expect(screen.getByText('Delete Application')).toBeInTheDocument()
  })

  it('does not render delete button when onDelete is not provided', () => {
    renderComponent()
    expect(screen.queryByText('Delete Application')).not.toBeInTheDocument()
  })

  it('renders credit profile when credit_utilization_pct is present', () => {
    renderComponent({
      application: { ...mockApplication, credit_utilization_pct: 0.45 },
    })
    expect(screen.getByText('Credit Profile')).toBeInTheDocument()
    expect(screen.getByText('45%')).toBeInTheDocument()
  })

  it('does not render credit profile when no credit data', () => {
    renderComponent()
    expect(screen.queryByText('Credit Profile')).not.toBeInTheDocument()
  })

  it('renders status badge with correct text', () => {
    renderComponent()
    expect(screen.getByText('PENDING')).toBeInTheDocument()
  })

  it('renders home loan fields when purpose is home', () => {
    renderComponent({
      application: {
        ...mockApplication,
        purpose: 'home',
        property_value: 500000,
        deposit_amount: 100000,
      },
    })
    expect(screen.getByText('Property Value')).toBeInTheDocument()
    expect(screen.getByText('Deposit')).toBeInTheDocument()
    expect(screen.getByText('LVR')).toBeInTheDocument()
  })
})
