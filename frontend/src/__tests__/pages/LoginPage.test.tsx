import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthContext } from '@/lib/auth'

const mockLogin = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/login',
  useSearchParams: () => new URLSearchParams(),
}))

import LoginPage from '@/app/(auth)/login/page'

function renderPage() {
  return render(
    <AuthContext.Provider value={{ user: null, isLoading: false, login: mockLogin, register: vi.fn(), logout: vi.fn() }}>
      <LoginPage />
    </AuthContext.Provider>
  )
}

describe('LoginPage', () => {
  beforeEach(() => { mockLogin.mockReset() })

  it('renders the login form with username and password fields', () => {
    renderPage()
    expect(screen.getByText('Welcome back')).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign In' })).toBeInTheDocument()
  })

  it('calls login with username and password on submit', async () => {
    const user = userEvent.setup()
    mockLogin.mockResolvedValue(undefined)
    renderPage()
    await user.type(screen.getByLabelText('Username'), 'testuser')
    await user.type(screen.getByLabelText('Password'), 'password123')
    await user.click(screen.getByRole('button', { name: 'Sign In' }))
    await waitFor(() => { expect(mockLogin).toHaveBeenCalledWith('testuser', 'password123') })
  })

  it('displays error message when login fails', async () => {
    const user = userEvent.setup()
    mockLogin.mockRejectedValue({ response: { data: { detail: 'Invalid credentials' } } })
    renderPage()
    await user.type(screen.getByLabelText('Username'), 'baduser')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign In' }))
    await waitFor(() => { expect(screen.getByText('Invalid credentials')).toBeInTheDocument() })
  })

  it('displays generic error when no detail in response', async () => {
    const user = userEvent.setup()
    mockLogin.mockRejectedValue(new Error('Network error'))
    renderPage()
    await user.type(screen.getByLabelText('Username'), 'testuser')
    await user.type(screen.getByLabelText('Password'), 'pass')
    await user.click(screen.getByRole('button', { name: 'Sign In' }))
    await waitFor(() => { expect(screen.getByText('Invalid credentials. Please try again.')).toBeInTheDocument() })
  })

  it('has a link to the register page', () => {
    renderPage()
    expect(screen.getByRole('link', { name: 'Create one' })).toHaveAttribute('href', '/register')
  })
  it('prompts for a 2FA code when the account requires one and re-submits with it', async () => {
    const user = userEvent.setup()
    mockLogin
      .mockResolvedValueOnce({ status: 'otp_required' })
      .mockResolvedValueOnce({ status: 'ok' })
    renderPage()
    await user.type(screen.getByLabelText('Username'), 'officer1')
    await user.type(screen.getByLabelText('Password'), 'pw')
    await user.click(screen.getByRole('button', { name: 'Sign In' }))

    const codeInput = await screen.findByLabelText('Authentication code')
    // Not treated as a failed login
    expect(screen.queryByText(/Invalid credentials/)).not.toBeInTheDocument()

    await user.type(codeInput, '123456')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    await waitFor(() => { expect(mockLogin).toHaveBeenLastCalledWith('officer1', 'pw', '123456') })
  })

  it('shows the server error when the 2FA code is wrong and stays on the code step', async () => {
    const user = userEvent.setup()
    mockLogin
      .mockResolvedValueOnce({ status: 'otp_required' })
      .mockRejectedValueOnce({ response: { data: { detail: 'Invalid two-factor authentication code.' } } })
    renderPage()
    await user.type(screen.getByLabelText('Username'), 'officer1')
    await user.type(screen.getByLabelText('Password'), 'pw')
    await user.click(screen.getByRole('button', { name: 'Sign In' }))
    await user.type(await screen.findByLabelText('Authentication code'), '000000')
    await user.click(screen.getByRole('button', { name: 'Verify' }))

    await waitFor(() => { expect(screen.getByText('Invalid two-factor authentication code.')).toBeInTheDocument() })
    expect(screen.getByLabelText('Authentication code')).toBeInTheDocument()
  })
})
