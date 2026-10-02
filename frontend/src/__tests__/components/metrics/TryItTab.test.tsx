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
