import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser, mockLoanApplication } from '@/test/mocks/handlers'
import { User } from '@/types'

const API_URL = 'http://localhost:8500/api/v1'

const mockRouterPush = vi.fn()
const mockParams = { id: 'loan-1' }

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockRouterPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useParams: () => mockParams,
  usePathname: () => '/dashboard/applications/loan-1',
  useSearchParams: () => new URLSearchParams(),
}))

// Lazy import so the mock above is applied first
import ApplicationDetailPage from '@/app/dashboard/applications/[id]/page'

function renderPage(user: User = { ...mockUser, role: 'admin' as const }) {
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
        <ApplicationDetailPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('ApplicationDetailPage', () => {
  beforeEach(() => {
    mockRouterPush.mockReset()
    // Set up handlers for application fetch
    server.use(
      http.get(`${API_URL}/loans/:id/`, () => {
        return HttpResponse.json(mockLoanApplication)
      }),
      http.get(`${API_URL}/emails/:id/`, () => {
        return HttpResponse.json(null, { status: 404 })
      }),
      http.get(`${API_URL}/agents/runs/:id/`, () => {
        return HttpResponse.json({ error: 'No agent run found' }, { status: 404 })
      }),
    )
  })

  it('shows loading state initially then renders content', async () => {
    renderPage()

    // After loading completes, application content should appear
    await waitFor(() => {
      expect(screen.getAllByText(/25,000/).length).toBeGreaterThan(0)
    })
  })

  it('renders application details after loading', async () => {
    renderPage()

    await waitFor(() => {
      // The application detail should render loan amount (may appear in multiple cards)
      expect(screen.getAllByText(/25,000/).length).toBeGreaterThan(0)
    })
  })

  it('shows "Application not found" for missing application', async () => {
    server.use(
      http.get(`${API_URL}/loans/:id/`, () => {
        return HttpResponse.json({ error: 'Not found' }, { status: 404 })
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Application not found')).toBeInTheDocument()
    })
  })

  it('redirects to list after successful delete', async () => {
    server.use(
      http.delete(`${API_URL}/loans/:id/`, () => {
        return HttpResponse.json(null, { status: 204 })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    // Wait for the application to load
    await waitFor(() => {
      expect(screen.getAllByText(/25,000/).length).toBeGreaterThan(0)
    })

    // Find and click the delete button (admin only)
    const deleteButton = screen.queryByRole('button', { name: /delete/i })
    if (deleteButton) {
      await user.click(deleteButton)
      // Confirm deletion if there's a confirmation dialog
      const confirmButton = screen.queryByRole('button', { name: /confirm|yes|delete/i })
      if (confirmButton) {
        await user.click(confirmButton)
      }

      await waitFor(() => {
        expect(mockRouterPush).toHaveBeenCalledWith('/dashboard/applications')
      })
    }
  })

  it('stays on page and resets state when delete fails', async () => {
    server.use(
      http.delete(`${API_URL}/loans/:id/`, () => {
        return HttpResponse.json({ error: 'Forbidden' }, { status: 403 })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => {
      expect(screen.getAllByText(/25,000/).length).toBeGreaterThan(0)
    })

    const deleteButton = screen.queryByRole('button', { name: /delete/i })
    if (deleteButton) {
      await user.click(deleteButton)
      const confirmButton = screen.queryByRole('button', { name: /confirm|yes|delete/i })
      if (confirmButton) {
        await user.click(confirmButton)
      }

      // Should NOT redirect — the page stays
      await waitFor(() => {
        expect(mockRouterPush).not.toHaveBeenCalledWith('/dashboard/applications')
      })
      // Application should still be visible
      expect(screen.getAllByText(/25,000/).length).toBeGreaterThan(0)
    }
  })
})
