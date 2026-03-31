import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EmailPreview, FormattedEmailBody } from '@/components/emails/EmailPreview'
import { GeneratedEmail } from '@/types'
import { emailApi } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  emailApi: { sendLatest: vi.fn() },
}))

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

  it('shows "Send Email" button only when guardrails passed', () => {
    render(<EmailPreview email={baseEmail} />)

    expect(screen.getByRole('button', { name: /send email/i })).toBeInTheDocument()
  })

  it('hides "Send Email" button when guardrails failed', () => {
    const failedEmail = { ...baseEmail, passed_guardrails: false }
    render(<EmailPreview email={failedEmail} />)

    expect(screen.queryByRole('button', { name: /send email/i })).not.toBeInTheDocument()
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

  it('calls emailApi.sendLatest on send click and shows success', async () => {
    const user = userEvent.setup()
    vi.mocked(emailApi.sendLatest).mockResolvedValueOnce({
      data: { recipient: 'jane@example.com' },
    } as any)

    render(<EmailPreview email={baseEmail} />)

    await user.click(screen.getByRole('button', { name: /send email/i }))

    expect(emailApi.sendLatest).toHaveBeenCalledWith('app-123')
    expect(await screen.findByText('Sent to jane@example.com')).toBeInTheDocument()
  })

  it('shows error state when send fails', async () => {
    const user = userEvent.setup()
    vi.mocked(emailApi.sendLatest).mockRejectedValueOnce({
      response: { data: { error: 'Recipient not found' } },
    })

    render(<EmailPreview email={baseEmail} />)

    await user.click(screen.getByRole('button', { name: /send email/i }))

    expect(await screen.findByText('Recipient not found')).toBeInTheDocument()
  })

  it('shows generic error when send fails without response data', async () => {
    const user = userEvent.setup()
    vi.mocked(emailApi.sendLatest).mockRejectedValueOnce(new Error('Network error'))

    render(<EmailPreview email={baseEmail} />)

    await user.click(screen.getByRole('button', { name: /send email/i }))

    expect(await screen.findByText('Network error')).toBeInTheDocument()
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

  it('renders bullet points with bullet marker', () => {
    render(<FormattedEmailBody body="• Submit your ID" />)

    expect(screen.getByText('Submit your ID')).toBeInTheDocument()
    expect(screen.getByText('•')).toBeInTheDocument()
  })

  it('renders bullet points with key:value format', () => {
    render(<FormattedEmailBody body="• Amount: $50,000" />)

    expect(screen.getByText('Amount:')).toBeInTheDocument()
    expect(screen.getByText('$50,000')).toBeInTheDocument()
  })

  it('bolds closing lines like "Kind regards,"', () => {
    render(<FormattedEmailBody body="Kind regards," />)

    const closing = screen.getByText('Kind regards,')
    expect(closing.tagName).toBe('STRONG')
  })

  it('bolds "Warm regards," closing', () => {
    render(<FormattedEmailBody body="Warm regards," />)

    const closing = screen.getByText('Warm regards,')
    expect(closing.tagName).toBe('STRONG')
  })

  it('renders empty lines as spacers', () => {
    const { container } = render(<FormattedEmailBody body={'Line one\n\nLine two'} />)

    // The empty line should render as a span with "h-3" in its className
    const allSpans = container.querySelectorAll('span')
    const spacers = Array.from(allSpans).filter((s) => s.className.includes('h-3'))
    expect(spacers.length).toBeGreaterThanOrEqual(1)
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
