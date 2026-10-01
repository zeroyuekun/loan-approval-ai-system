import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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

let queryClient: QueryClient

function renderWithAuth() {
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    </QueryClientProvider>
  )
}

const DRAFT_KEY = 'loan_application_draft'

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

  it('logs out user when refresh token is also expired (double-401)', async () => {
    // Start authenticated
    renderWithAuth()
    await waitFor(() => {
      expect(screen.getByTestId('user')).toHaveTextContent(mockUser.username)
    })

    // Now make /auth/me/ return 401 — simulates session expiry detected on next profile refresh
    server.use(
      http.get(`${API_URL}/auth/me/`, () => {
        return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      }),
      // Refresh token is also expired
      http.post(`${API_URL}/auth/refresh/`, () => {
        return HttpResponse.json({ detail: 'Token expired' }, { status: 401 })
      })
    )

    // Trigger a profile re-fetch (simulates the hook re-running)
    const user = userEvent.setup()
    await user.click(screen.getByText('Logout'))

    // After logout (which calls /auth/logout/ then clears state), user should be null
    await waitFor(() => {
      expect(screen.getByTestId('user')).toHaveTextContent('null')
    })
    expect(sessionStorage.getItem('user')).toBeNull()
  })
  it('logout clears the query cache and per-user local storage', async () => {
    const user = userEvent.setup()
    renderWithAuth()
    await waitFor(() => {
      expect(screen.getByTestId('user')).toHaveTextContent(mockUser.username)
    })

    queryClient.setQueryData(['customerProfile'], { address_line_1: '1 Private Rd' })
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ savedAt: Date.now(), owner: mockUser.username, data: { annual_income: 1 } }))

    await user.click(screen.getByText('Logout'))

    await waitFor(() => {
      expect(screen.getByTestId('user')).toHaveTextContent('null')
    })
    expect(queryClient.getQueryData(['customerProfile'])).toBeUndefined()
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull()
  })

  it('login clears cached data and a draft left by a different user', async () => {
    server.use(
      http.get(`${API_URL}/auth/me/`, () => HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })),
      http.post(`${API_URL}/auth/refresh/`, () => HttpResponse.json({ detail: 'expired' }, { status: 401 })),
    )
    const user = userEvent.setup()
    renderWithAuth()
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })

    // Left behind by another customer on this browser
    queryClient.setQueryData(['customerProfile'], { address_line_1: '1 Private Rd' })
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ savedAt: Date.now(), owner: 'someone_else', data: { annual_income: 1 } }))

    server.use(
      http.post(`${API_URL}/auth/login/`, () => HttpResponse.json({ user: mockUser })),
    )
    await user.click(screen.getByText('Login'))

    await waitFor(() => {
      expect(screen.getByTestId('user')).toHaveTextContent(mockUser.username)
    })
    expect(queryClient.getQueryData(['customerProfile'])).toBeUndefined()
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull()
  })

  it('login keeps a draft owned by the user signing in', async () => {
    server.use(
      http.get(`${API_URL}/auth/me/`, () => HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })),
      http.post(`${API_URL}/auth/refresh/`, () => HttpResponse.json({ detail: 'expired' }, { status: 401 })),
    )
    const user = userEvent.setup()
    renderWithAuth()
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    const ownDraft = JSON.stringify({ savedAt: Date.now(), owner: mockUser.username, data: { annual_income: 1 } })
    localStorage.setItem(DRAFT_KEY, ownDraft)

    server.use(
      http.post(`${API_URL}/auth/login/`, () => HttpResponse.json({ user: mockUser })),
    )
    await user.click(screen.getByText('Login'))

    await waitFor(() => {
      expect(screen.getByTestId('user')).toHaveTextContent(mockUser.username)
    })
    expect(localStorage.getItem(DRAFT_KEY)).toBe(ownDraft)
  })
})
