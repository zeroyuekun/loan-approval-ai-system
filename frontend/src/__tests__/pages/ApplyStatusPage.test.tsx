import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockCustomerUser, mockLoanApplication } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  useParams: () => ({ id: 'loan-1' }),
  usePathname: () => '/apply/status/loan-1',
  useSearchParams: () => new URLSearchParams(),
}))

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
  it('shows masked money values verbatim instead of $NaN', async () => {
    server.use(http.get(`${API_URL}/loans/loan-1/`, () => HttpResponse.json(maskedApplication)))
    renderWithProviders(<CustomerApplicationStatusPage />)

    await screen.findByText('Loan Amount')
    expect(screen.getByText('Under $50,000')).toBeInTheDocument()
    expect(screen.getByText('$50,000 - $100,000')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/NaN/)
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
