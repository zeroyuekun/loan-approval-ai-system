import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApplicationForm } from '@/components/applications/ApplicationForm'
import { AuthContext } from '@/lib/auth'
import { User } from '@/types'

const mockRouterPush = vi.fn()
const mockRouterReplace = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockRouterPush,
    replace: mockRouterReplace,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}))

// Mock useCreateApplication to avoid hitting the real API
const mockMutateAsync = vi.fn()
vi.mock('@/hooks/useApplications', () => ({
  useCreateApplication: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
    isError: false,
  }),
}))

const adminUser: User = {
  id: 1,
  username: 'admin',
  email: 'admin@example.com',
  role: 'admin',
  first_name: 'Admin',
  last_name: 'User',
}

function renderForm(user: User = adminUser) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={{
        user,
        isLoading: false,
        login: vi.fn(),
        register: vi.fn(),
        logout: vi.fn(),
      }}>
        <ApplicationForm />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('ApplicationForm', () => {
  beforeEach(() => {
    mockMutateAsync.mockReset()
    mockRouterPush.mockReset()
    localStorage.clear()
  })

  it('renders step 1 with personal information fields', () => {
    renderForm()

    expect(screen.getByText('Personal Information')).toBeInTheDocument()
    // Step indicator should show step labels
    expect(screen.getByText('Personal')).toBeInTheDocument()
    // Should have the disabled name fields from user context
    expect(screen.getByDisplayValue('Admin')).toBeInTheDocument()
    expect(screen.getByDisplayValue('User')).toBeInTheDocument()
    // Navigation buttons
    expect(screen.getByText('Previous')).toBeDisabled()
    expect(screen.getByText('Next')).toBeInTheDocument()
  })

  it('navigates from step 1 to step 2 on Next click', async () => {
    const user = userEvent.setup()
    renderForm()

    expect(screen.getByRole('heading', { name: 'Personal Information' })).toBeInTheDocument()

    await user.click(screen.getByText('Next'))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Employment & Income' })).toBeInTheDocument()
    })
  })

  it('shows validation errors when required fields are invalid on step 2', async () => {
    const user = userEvent.setup()
    renderForm()

    // Navigate to step 2
    await user.click(screen.getByText('Next'))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Employment & Income' })).toBeInTheDocument()
    })

    // Clear annual income (set to empty/0 which is invalid since min is 1)
    const incomeInput = screen.getByLabelText('Gross Annual Income (A$)')
    await user.clear(incomeInput)

    // Try to advance - should show validation error
    await user.click(screen.getByText('Next'))

    await waitFor(() => {
      expect(screen.getByText('Gross annual income is required')).toBeInTheDocument()
    })
  })

  it('submits the form on the final step', async () => {
    mockMutateAsync.mockResolvedValue({ id: 'new-loan-123' })
    const user = userEvent.setup()
    renderForm()

    // Navigate through all steps using heading queries to avoid duplicate text
    // Step 1 -> 2
    await user.click(screen.getByText('Next'))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Employment & Income' })).toBeInTheDocument()
    })

    // Fill required step 2 fields
    const incomeInput = screen.getByLabelText('Gross Annual Income (A$)')
    await user.clear(incomeInput)
    await user.type(incomeInput, '85000')

    const creditInput = screen.getByLabelText('Equifax Credit Score (0\u20131200)')
    await user.clear(creditInput)
    await user.type(creditInput, '750')

    // Step 2 -> 3
    await user.click(screen.getByText('Next'))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Expenses/i })).toBeInTheDocument()
    })

    // Step 3 -> 4
    await user.click(screen.getByText('Next'))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Loan Details' })).toBeInTheDocument()
    })

    // Fill loan amount (required, min 1)
    const loanAmountInput = screen.getByLabelText('Loan Amount (A$)')
    await user.clear(loanAmountInput)
    await user.type(loanAmountInput, '25000')

    // Step 4 -> 5 (Review)
    await user.click(screen.getByText('Next'))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Review/i })).toBeInTheDocument()
    })

    // Submit
    await user.click(screen.getByText('Submit Application'))

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalled()
    })

    await waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith('/dashboard/applications/new-loan-123')
    })
  })
})
