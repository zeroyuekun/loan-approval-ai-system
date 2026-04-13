import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthContext } from '@/lib/auth'
import { expectNoAxeViolations } from '@/test/axe-helper'

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

  it('renders the login form with username and password fields', async () => {
    const { container } = renderPage()
    expect(screen.getByText('Welcome back')).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign In' })).toBeInTheDocument()
    await expectNoAxeViolations(container)
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
})
