import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TryItTab } from '@/components/metrics/tabs/TryItTab'

const scoreApplicant = vi.fn()
vi.mock('@/lib/api', () => ({ mlApi: { scoreApplicant: (...a: unknown[]) => scoreApplicant(...a) } }))

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <TryItTab />
    </QueryClientProvider>,
  )
}

const FIXED_RESPONSE = {
  probability: 0.7321,
  decision: 'approved' as const,
  threshold: 0.45,
  risk_grade: 'B',
  top_factors: [
    { feature: 'credit_score', impact: 0.12 },
    { feature: 'debt_to_income', impact: -0.05 },
  ],
  model_version: 'xgboost-1.4.0',
  note: 'Scored on the facts entered here. Credit bureau, banking and economic features are not collected on this form and use the model\'s training defaults, so a real application with that data on file can score differently.',
  defaulted_features: ['num_defaults_5yr', 'savings_balance', 'credit_history_months'],
  policy_mode: 'shadow',
  policy_hard_fails: [] as string[],
  policy_refers: [] as string[],
  refer_reasons: [] as string[],
}

describe('TryItTab', () => {
  beforeEach(() => {
    scoreApplicant.mockReset()
  })

  it('submits the prefilled sample applicant and renders the probability, decision, note and defaulted count', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockResolvedValueOnce({ data: FIXED_RESPONSE })
    renderTab()

    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    await waitFor(() => expect(scoreApplicant).toHaveBeenCalledTimes(1))

    expect(await screen.findByText(/73\.2%/)).toBeInTheDocument()
    expect(screen.getByText(/approved/i)).toBeInTheDocument()
    expect(screen.getByText(FIXED_RESPONSE.note)).toBeInTheDocument()
    expect(screen.getByText(/3 model features used default values/i)).toBeInTheDocument()
  })

  it('labels the probability as the approval probability and shows the implied default probability', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockResolvedValueOnce({ data: FIXED_RESPONSE })
    renderTab()

    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    expect(await screen.findByText('Approval probability')).toBeInTheDocument()
    expect(screen.queryByText(/probability of default/i)).not.toBeInTheDocument()
    expect(screen.getByText(/estimated default probability/i)).toHaveTextContent('26.8%')
  })

  it('sends a consistent home-loan sample including property value, deposit and expenses', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockResolvedValueOnce({ data: FIXED_RESPONSE })
    renderTab()

    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    await waitFor(() => expect(scoreApplicant).toHaveBeenCalledTimes(1))
    const payload = scoreApplicant.mock.calls[0][0]
    expect(payload.purpose).toBe('home')
    expect(payload.property_value).toBe(600000)
    expect(payload.deposit_amount).toBe(150000)
    expect(payload.monthly_expenses).toBe(3000)
    expect(payload.loan_amount).toBeLessThanOrEqual(payload.property_value)
  })

  it('omits an emptied field instead of sending 0', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockResolvedValueOnce({ data: FIXED_RESPONSE })
    renderTab()

    await user.clear(screen.getByLabelText(/monthly expenses/i))
    await user.clear(screen.getByLabelText(/^loan amount/i))
    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    await waitFor(() => expect(scoreApplicant).toHaveBeenCalledTimes(1))
    const payload = scoreApplicant.mock.calls[0][0]
    expect(payload).not.toHaveProperty('monthly_expenses')
    expect(payload).not.toHaveProperty('loan_amount')
    expect(payload.annual_income).toBe(95000)
  })

  it('hides the property fields for a non-home purpose and does not send them', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockResolvedValueOnce({ data: FIXED_RESPONSE })
    renderTab()

    await user.selectOptions(screen.getByLabelText(/loan purpose/i), 'personal')
    expect(screen.queryByLabelText(/property value/i)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    await waitFor(() => expect(scoreApplicant).toHaveBeenCalledTimes(1))
    const payload = scoreApplicant.mock.calls[0][0]
    expect(payload).not.toHaveProperty('property_value')
    expect(payload).not.toHaveProperty('deposit_amount')
  })

  it('renders a 400 detail message inline', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { detail: 'These figures are inconsistent: Loan cannot exceed the property purchase price.' },
      },
    })
    renderTab()

    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    const message = await screen.findByText(/loan cannot exceed the property purchase price/i)
    expect(message).toBeInTheDocument()
    expect(message.textContent).not.toMatch(/^detail:/i)
  })

  it('shows a policy rules line when the overlay evaluated P-codes', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockResolvedValueOnce({
      data: {
        ...FIXED_RESPONSE,
        decision: 'denied',
        policy_mode: 'enforce',
        policy_hard_fails: ['P01'],
        policy_refers: ['P11'],
        refer_reasons: ['POLICY_REFER_P11'],
      },
    })
    renderTab()

    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    const line = await screen.findByText(/policy rules/i)
    expect(line.closest('div')).toHaveTextContent(/P01/)
    expect(line.closest('div')).toHaveTextContent(/P11/)
  })

  it('has no policy rules line when no P-codes were evaluated', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockResolvedValueOnce({ data: FIXED_RESPONSE })
    renderTab()

    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    await screen.findByText('Approval probability')
    expect(screen.queryByText(/policy rules/i)).not.toBeInTheDocument()
  })

  it('renders the 503 "no active model" message inline without crashing', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockRejectedValueOnce({
      response: { status: 503, data: { detail: 'No active model' } },
    })
    renderTab()

    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    expect(await screen.findByText(/no active model/i)).toBeInTheDocument()
  })

  it('renders a 400 field error next to the offending field', async () => {
    const user = userEvent.setup()
    scoreApplicant.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { credit_score: ['Ensure this value is less than or equal to 1200.'] },
      },
    })
    renderTab()

    await user.click(screen.getByRole('button', { name: /score applicant/i }))

    expect(await screen.findByText(/ensure this value is less than or equal to 1200/i)).toBeInTheDocument()
  })
})
