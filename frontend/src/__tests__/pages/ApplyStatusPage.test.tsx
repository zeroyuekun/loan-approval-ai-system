import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { useParams } from 'next/navigation'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockCustomerUser, mockLoanApplication } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import CustomerApplicationStatusPage from '@/app/apply/status/[id]/page'
import CustomerApplyPage from '@/app/apply/page'

// What the customer-facing loan serializer returns: money and score are masked bands.
const maskedApplication = {
  ...mockLoanApplication,
  applicant: mockCustomerUser,
  status: 'pending',
  decision: null,
  annual_income: '$50,000 - $100,000',
  loan_amount: 'Under $50,000',
  credit_score: 'Average (500-699)',
  monthly_expenses: 'Under $50,000',
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider
        value={{ user: mockCustomerUser, isLoading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn() }}
      >
        {ui}
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

describe('Customer application status page', () => {
  beforeEach(() => {
    vi.mocked(useParams).mockReturnValue({ id: 'loan-1' })
  })

  it('shows masked money values verbatim instead of $NaN', async () => {
    server.use(http.get(`${API_URL}/loans/loan-1/`, () => HttpResponse.json(maskedApplication)))
    renderWithProviders(<CustomerApplicationStatusPage />)

    await screen.findByText('Loan Amount')
    expect(screen.getByText('Under $50,000')).toBeInTheDocument()
    expect(screen.getByText('$50,000 - $100,000')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/NaN/)
  })

  describe('when the pipeline dispatch failed (queue_failed)', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    it('explains the delay in plain words instead of "Status unknown."', async () => {
      server.use(
        http.get(`${API_URL}/loans/loan-1/`, () =>
          HttpResponse.json({ ...maskedApplication, status: 'queue_failed' }),
        ),
      )
      renderWithProviders(<CustomerApplicationStatusPage />)

      await screen.findByText('Loan Amount')
      expect(screen.queryByText('Status unknown.')).not.toBeInTheDocument()
      expect(screen.getByText(/received.*delayed/i)).toBeInTheDocument()
      expect(screen.queryByText(/queue_failed/i)).not.toBeInTheDocument()
    })

    it('keeps polling at the backend retry pace (60s), not the 5s in-flight pace', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      let requests = 0
      server.use(
        http.get(`${API_URL}/loans/loan-1/`, () => {
          requests += 1
          return HttpResponse.json({ ...maskedApplication, status: 'queue_failed' })
        }),
      )
      renderWithProviders(<CustomerApplicationStatusPage />)

      await screen.findByText('Loan Amount')
      expect(requests).toBe(1)
      await vi.advanceTimersByTimeAsync(5_000)
      expect(requests).toBe(1)
      await vi.advanceTimersByTimeAsync(55_000)
      expect(requests).toBe(2)
    })
  })

  describe('while the application is in flight (pending)', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    it('polls every 5s', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      let requests = 0
      server.use(
        http.get(`${API_URL}/loans/loan-1/`, () => {
          requests += 1
          return HttpResponse.json(maskedApplication)
        }),
      )
      renderWithProviders(<CustomerApplicationStatusPage />)

      await screen.findByText('Loan Amount')
      expect(requests).toBe(1)
      await vi.advanceTimersByTimeAsync(5_000)
      expect(requests).toBe(2)
    })
  })
})

describe('Customer applications list', () => {
  it('shows a masked loan amount verbatim instead of $NaN', async () => {
    server.use(
      http.get(`${API_URL}/loans/`, () =>
        HttpResponse.json({ count: 1, next: null, previous: null, results: [maskedApplication] }),
      ),
    )
    renderWithProviders(<CustomerApplyPage />)

    await screen.findByText('36 months')
    expect(screen.getByText('Under $50,000')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/NaN/)
  })
})
