import { render, screen } from '@testing-library/react'
import { EmailPreview, FormattedEmailBody } from '@/components/emails/EmailPreview'
import { GeneratedEmail } from '@/types'

vi.mock('@/components/emails/GuardrailLogDisplay', () => ({
  GuardrailLogDisplay: ({ checks }: any) => (
    <div data-testid="guardrail-log">{checks.length} checks</div>
  ),
}))

const baseEmail: GeneratedEmail = {
  id: 'email-1',
  application_id: 'app-123',
  applicant_name: 'Jane Doe',
  decision: 'approved',
  subject: 'Your Loan Has Been Approved',
  body: 'Dear Jane,\n\nCongratulations on your approval.\n\nLoan Details:\n  Loan Amount:  $50,000.00\n\nNext Steps:\n• Submit your ID\n• Sign the contract\n\nKind regards,\nSarah Mitchell\nSenior Lending Officer',
  model_used: 'claude-sonnet-4-20250514',
  passed_guardrails: true,
  attempt_number: 2,
  generation_time_ms: 1450,
  created_at: '2026-03-30T10:00:00Z',
  guardrail_checks: [
    { check_name: 'Tone Check', passed: true, details: 'OK' },
    { check_name: 'PII Check', passed: true, details: 'Clean' },
  ],
}

describe('EmailPreview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders subject, attempt number, and generation time', () => {
    render(<EmailPreview email={baseEmail} />)

    expect(screen.getByText('Your Loan Has Been Approved')).toBeInTheDocument()
    expect(screen.getByText('Attempt #2')).toBeInTheDocument()
    expect(screen.getByText('1450ms')).toBeInTheDocument()
  })

  it('shows "Passed Guardrails" badge when passed_guardrails is true', () => {
    render(<EmailPreview email={baseEmail} />)

    expect(screen.getByText('Passed Guardrails')).toBeInTheDocument()
    expect(screen.queryByText('Failed Guardrails')).not.toBeInTheDocument()
  })

  it('shows "Failed Guardrails" badge when passed_guardrails is false', () => {
    const failedEmail = { ...baseEmail, passed_guardrails: false }
    render(<EmailPreview email={failedEmail} />)

    expect(screen.getByText('Failed Guardrails')).toBeInTheDocument()
    expect(screen.queryByText('Passed Guardrails')).not.toBeInTheDocument()
  })

  it('renders guardrail checks via GuardrailLogDisplay', () => {
    render(<EmailPreview email={baseEmail} />)

    expect(screen.getByTestId('guardrail-log')).toHaveTextContent('2 checks')
  })

  it('does not render GuardrailLogDisplay when no checks present', () => {
    const noChecks = { ...baseEmail, guardrail_checks: [] }
    render(<EmailPreview email={noChecks} />)

    expect(screen.queryByTestId('guardrail-log')).not.toBeInTheDocument()
  })
})

describe('FormattedEmailBody', () => {
  it('bolds "Dear " greeting lines', () => {
    render(<FormattedEmailBody body="Dear Jane," />)

    const strong = screen.getByText('Dear Jane,')
    expect(strong.tagName).toBe('STRONG')
  })

  it('bolds section headers like "Loan Details:" and "Next Steps:"', () => {
    render(<FormattedEmailBody body={'Loan Details:\nNext Steps:'} />)

    const loanDetails = screen.getByText('Loan Details:')
    expect(loanDetails.tagName).toBe('STRONG')

    const nextSteps = screen.getByText('Next Steps:')
    expect(nextSteps.tagName).toBe('STRONG')
  })

  it('renders bullet points as plain text', () => {
    render(<FormattedEmailBody body="• Submit your ID" />)

    expect(screen.getByText('• Submit your ID')).toBeInTheDocument()
  })

  it('renders bullet points with key:value as plain text', () => {
    render(<FormattedEmailBody body="• Amount: $50,000" />)

    expect(screen.getByText('• Amount: $50,000')).toBeInTheDocument()
  })

  it('renders closing lines like "Kind regards," as plain text', () => {
    render(<FormattedEmailBody body="Kind regards," />)

    const closing = screen.getByText('Kind regards,')
    expect(closing.tagName).toBe('SPAN')
  })

  it('renders "Warm regards," closing as plain text', () => {
    render(<FormattedEmailBody body="Warm regards," />)

    const closing = screen.getByText('Warm regards,')
    expect(closing.tagName).toBe('SPAN')
  })

  it('renders empty lines as spans', () => {
    const { container } = render(<FormattedEmailBody body={'Line one\n\nLine two'} />)

    // The empty line renders as a span via renderLineWithInlineBold
    const allSpans = container.querySelectorAll('span')
    // Should have at least 3 spans: "Line one", empty line, "Line two"
    expect(allSpans.length).toBeGreaterThanOrEqual(3)
  })

  it('renders signature lines without bold', () => {
    render(<FormattedEmailBody body={'Sarah Mitchell\nSenior Lending Officer'} />)

    const name = screen.getByText('Sarah Mitchell')
    expect(name.tagName).toBe('SPAN')
    expect(name.querySelector('strong')).toBeNull()

    const title = screen.getByText('Senior Lending Officer')
    expect(title.tagName).toBe('SPAN')
    expect(title.querySelector('strong')).toBeNull()
  })
})
