import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NewApplicationPage from '@/app/apply/new/page'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/apply/new',
}))

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  )
}

describe('NewApplicationPage', () => {
  it('renders page heading', () => {
    renderWithProviders(<NewApplicationPage />)

    expect(screen.getByText('New Loan Application')).toBeInTheDocument()
    expect(screen.getByText(/Fill in the details below/)).toBeInTheDocument()
  })

  it('renders the application form', () => {
    renderWithProviders(<NewApplicationPage />)

    // ApplicationForm renders step indicators
    expect(screen.getByText('Personal')).toBeInTheDocument()
  })
})
