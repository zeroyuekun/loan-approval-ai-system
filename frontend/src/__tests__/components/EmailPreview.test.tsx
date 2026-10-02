import { render, screen } from '@testing-library/react'
import { renderToString } from 'react-dom/server'
import { EmailPreview, HtmlEmailBody, formatEmailTime } from '@/components/emails/EmailPreview'
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
  html_body: '<div style="font-family: Arial; font-size: 14px;"><p><strong>Dear Jane,</strong></p><p>Congratulations on your approval.</p></div>',
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

  it('renders subject in email header, sender name, and generation time', () => {
    render(<EmailPreview email={baseEmail} />)

    expect(screen.getByText('Your Loan Has Been Approved')).toBeInTheDocument()
    expect(screen.getByText('Sarah Mitchell')).toBeInTheDocument()
    expect(screen.getByText('1450ms')).toBeInTheDocument()
  })

  it('renders the from address in email header', () => {
    render(<EmailPreview email={baseEmail} />)

    expect(screen.getByText(/decisions@aussieloanai\.com\.au/)).toBeInTheDocument()
  })

  it('shows "Passed" badge when passed_guardrails is true', () => {
    render(<EmailPreview email={baseEmail} />)

    expect(screen.getByText('Passed')).toBeInTheDocument()
    expect(screen.queryByText('Failed')).not.toBeInTheDocument()
  })

  it('shows "Failed" badge when passed_guardrails is false', () => {
    const failedEmail = { ...baseEmail, passed_guardrails: false }
    render(<EmailPreview email={failedEmail} />)

    expect(screen.getByText('Failed')).toBeInTheDocument()
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

  it('renders HTML preview when html_body is provided', () => {
    const { container } = render(<EmailPreview email={baseEmail} />)

    const preview = container.querySelector('.email-html-preview')
    expect(preview).toBeInTheDocument()
    expect(preview?.innerHTML).toContain('Dear Jane,')
  })

  it('falls back to paragraph HTML when no html_body', () => {
    const plainOnly = { ...baseEmail, html_body: undefined }
    const { container } = render(<EmailPreview email={plainOnly} />)

    const preview = container.querySelector('.email-html-preview')
    expect(preview).toBeInTheDocument()
  })
})

describe('HtmlEmailBody', () => {
  it('sanitizes and renders HTML content', () => {
    const { container } = render(
      <HtmlEmailBody html='<p>Hello <strong>World</strong></p>' />
    )
    const preview = container.querySelector('.email-html-preview')
    expect(preview).toBeInTheDocument()
    expect(preview?.querySelector('strong')?.textContent).toBe('World')
  })

  it('strips disallowed tags', () => {
    const { container } = render(
      <HtmlEmailBody html='<p>Safe</p><script>alert("xss")</script>' />
    )
    const preview = container.querySelector('.email-html-preview')
    expect(preview?.innerHTML).not.toContain('script')
    expect(preview?.textContent).toContain('Safe')
  })
})

describe('email preview timestamp and server rendering', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows when the email was created, not the current time', () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-01T23:59:00Z'))
    render(<EmailPreview email={baseEmail} />)
    expect(screen.getByText(formatEmailTime(baseEmail.created_at))).toBeInTheDocument()
    expect(formatEmailTime(baseEmail.created_at)).not.toBe(formatEmailTime(new Date().toISOString()))
  })

  it('formatEmailTime renders the local date and time of an ISO timestamp', () => {
    const d = new Date('2026-03-30T10:05:00Z')
    const out = formatEmailTime('2026-03-30T10:05:00Z')
    const h = d.getHours() % 12 || 12
    expect(out).toContain(`${h}:05 ${d.getHours() >= 12 ? 'PM' : 'AM'}`)
    expect(out).toContain(String(d.getDate()))
  })

  it('emits no email HTML during server rendering (sanitiser needs a DOM)', () => {
    const html = renderToString(<HtmlEmailBody html='<p>Body text</p><img src=x onerror="alert(1)">' />)
    expect(html).not.toContain('Body text')
    expect(html).not.toContain('onerror')
  })
})

