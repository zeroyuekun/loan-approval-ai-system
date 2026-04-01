import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { AuthProvider } from '@/hooks/useAuth'
import { useAuth } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

// A test consumer that exposes auth state
function AuthConsumer() {
  const { user, isLoading, login, logout } = useAuth()
  return (
    <div>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="user">{user ? JSON.stringify(user) : 'null'}</span>
      <button onClick={() => login('testuser', 'password123')}>Login</button>
      <button onClick={() => logout()}>Logout</button>
    </div>
  )
}

function renderWithAuth() {
  return render(
    <AuthProvider>
      <AuthConsumer />
    </AuthProvider>
  )
}

describe('useAuth', () => {
  it('restores session from server profile on mount', async () => {
    renderWithAuth()

    // Initially loading
    expect(screen.getByTestId('loading')).toHaveTextContent('true')

    // After profile fetch resolves
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('user')).toHaveTextContent(mockUser.username)
  })

  it('logs in successfully and stores user', async () => {
    // Start with failed profile (not logged in yet)
    server.use(
      http.get(`${API_URL}/auth/me/`, () => {
        return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      })
    )

    const user = userEvent.setup()
    renderWithAuth()

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('user')).toHaveTextContent('null')

    // Now restore the normal login handler
    server.use(
      http.post(`${API_URL}/auth/login/`, () => {
        return HttpResponse.json({ user: mockUser, detail: 'Login successful' })
      })
    )

    await user.click(screen.getByText('Login'))

    await waitFor(() => {
      expect(screen.getByTestId('user')).toHaveTextContent(mockUser.username)
    })
    // Session storage should have the user
    expect(sessionStorage.getItem('user')).toContain(mockUser.username)
  })

  it('logs out and clears user state', async () => {
    const user = userEvent.setup()
    renderWithAuth()

    // Wait for session restore
    await waitFor(() => {
      expect(screen.getByTestId('user')).toHaveTextContent(mockUser.username)
    })

    await user.click(screen.getByText('Logout'))

    await waitFor(() => {
      expect(screen.getByTestId('user')).toHaveTextContent('null')
    })
    expect(sessionStorage.getItem('user')).toBeNull()
  })

  it('sets user to null when profile fetch fails', async () => {
    server.use(
      http.get(`${API_URL}/auth/me/`, () => {
        return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      })
    )

    renderWithAuth()

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('user')).toHaveTextContent('null')
  })
})
