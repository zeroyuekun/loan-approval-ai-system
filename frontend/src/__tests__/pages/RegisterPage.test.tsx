import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthContext } from '@/lib/auth'

const mockRegister = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/register',
  useSearchParams: () => new URLSearchParams(),
}))

import RegisterPage from '@/app/(auth)/register/page'

function renderPage() {
  return render(
    <AuthContext.Provider value={{ user: null, isLoading: false, login: vi.fn(), register: mockRegister, logout: vi.fn() }}>
      <RegisterPage />
    </AuthContext.Provider>
  )
}

describe('RegisterPage', () => {
  beforeEach(() => { mockRegister.mockReset() })

  it('renders all form fields', () => {
    renderPage()
    expect(screen.getByText('Create account')).toBeInTheDocument()
    expect(screen.getByLabelText('First Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Last Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByLabelText('Confirm Password')).toBeInTheDocument()
  })

  it('shows error when passwords do not match', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.type(screen.getByLabelText('First Name'), 'John')
    await user.type(screen.getByLabelText('Last Name'), 'Doe')
    await user.type(screen.getByLabelText('Username'), 'johndoe')
    await user.type(screen.getByLabelText('Email'), 'john@example.com')
    await user.type(screen.getByLabelText('Password'), 'password123')
    await user.type(screen.getByLabelText('Confirm Password'), 'different')
    await user.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(screen.getByText('Passwords do not match')).toBeInTheDocument()
    expect(mockRegister).not.toHaveBeenCalled()
  })

  it('calls register with correct payload on valid submit', async () => {
    const user = userEvent.setup()
    mockRegister.mockResolvedValue(undefined)
    renderPage()
    await user.type(screen.getByLabelText('First Name'), 'John')
    await user.type(screen.getByLabelText('Last Name'), 'Doe')
    await user.type(screen.getByLabelText('Username'), 'johndoe')
    await user.type(screen.getByLabelText('Email'), 'john@example.com')
    await user.type(screen.getByLabelText('Password'), 'password123')
    await user.type(screen.getByLabelText('Confirm Password'), 'password123')
    await user.click(screen.getByRole('button', { name: 'Create Account' }))
    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith({
        first_name: 'John', last_name: 'Doe', username: 'johndoe',
        email: 'john@example.com', password: 'password123', password2: 'password123',
      })
    })
  })

  it('displays API error messages on failure', async () => {
    const user = userEvent.setup()
    mockRegister.mockRejectedValue({ response: { data: { email: ['Email already in use'] } } })
    renderPage()
    await user.type(screen.getByLabelText('First Name'), 'John')
    await user.type(screen.getByLabelText('Last Name'), 'Doe')
    await user.type(screen.getByLabelText('Username'), 'johndoe')
    await user.type(screen.getByLabelText('Email'), 'taken@example.com')
    await user.type(screen.getByLabelText('Password'), 'password123')
    await user.type(screen.getByLabelText('Confirm Password'), 'password123')
    await user.click(screen.getByRole('button', { name: 'Create Account' }))
    await waitFor(() => { expect(screen.getByText('Email already in use')).toBeInTheDocument() })
  })

  it('has a link to the login page', () => {
    renderPage()
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
  })
})
