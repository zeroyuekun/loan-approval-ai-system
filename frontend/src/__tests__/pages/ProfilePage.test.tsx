import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser, mockCustomerProfile } from '@/test/mocks/handlers'
import { User } from '@/types'

const API_URL = 'http://localhost:8500/api/v1'

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/dashboard/profile',
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}))

import ProfilePage from '@/app/dashboard/profile/page'

function renderPage(user: User = { ...mockUser, role: 'customer' as const, first_name: 'Jane', last_name: 'Doe' }) {
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
        <ProfilePage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('ProfilePage', () => {
  beforeEach(() => {
    server.use(
      http.get(`${API_URL}/auth/me/profile/`, () => {
        return HttpResponse.json(mockCustomerProfile)
      }),
    )
  })

  it('renders profile form with user data populated', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('My Profile')).toBeInTheDocument()
    })

    // User name and email should show (disabled fields)
    expect(screen.getByDisplayValue('Jane Doe')).toBeInTheDocument()
    expect(screen.getByDisplayValue('test@example.com')).toBeInTheDocument()

    // Profile data should be populated in form fields
    await waitFor(() => {
      expect(screen.getByDisplayValue('0412345678')).toBeInTheDocument()
    })
    expect(screen.getByDisplayValue('123 Test St')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Sydney')).toBeInTheDocument()
    expect(screen.getByDisplayValue('2000')).toBeInTheDocument()

    // Banking relationship card
    expect(screen.getByText('Banking Relationship')).toBeInTheDocument()
    expect(screen.getByText('Gold Tier')).toBeInTheDocument()
    expect(screen.getByText('3 years')).toBeInTheDocument()
    expect(screen.getByText('98.0%')).toBeInTheDocument()
  })

  it('shows loading state while fetching', async () => {
    // Delay the response to see loading state
    server.use(
      http.get(`${API_URL}/auth/me/profile/`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 100))
        return HttpResponse.json(mockCustomerProfile)
      }),
    )

    renderPage()

    // Loading skeletons should be present initially
    // The page renders Skeleton components during loading
    const container = document.querySelector('.space-y-6')
    expect(container).toBeInTheDocument()

    // After loading, content should appear
    await waitFor(() => {
      expect(screen.getByText('My Profile')).toBeInTheDocument()
    })
  })

  it('handles profile update submission', async () => {
    let patchCalled = false
    let patchBody: any = null

    server.use(
      http.patch(`${API_URL}/auth/me/profile/`, async ({ request }) => {
        patchCalled = true
        patchBody = await request.json()
        return HttpResponse.json({ ...mockCustomerProfile, phone: '0499999999' })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => {
      expect(screen.getByDisplayValue('0412345678')).toBeInTheDocument()
    })

    // Update phone number
    const phoneInput = screen.getByDisplayValue('0412345678')
    await user.clear(phoneInput)
    await user.type(phoneInput, '0499999999')

    // Click save
    const saveButton = screen.getByRole('button', { name: /save changes/i })
    await user.click(saveButton)

    await waitFor(() => {
      expect(patchCalled).toBe(true)
    })
    expect(patchBody.phone).toBe('0499999999')
  })

  it('shows error state when profile update fails', async () => {
    server.use(
      http.patch(`${API_URL}/auth/me/profile/`, () => {
        return HttpResponse.json({ error: 'Validation error' }, { status: 400 })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('My Profile')).toBeInTheDocument()
    })

    const saveButton = screen.getByRole('button', { name: /save changes/i })
    await user.click(saveButton)

    await waitFor(() => {
      expect(screen.getByText(/Failed to save profile/)).toBeInTheDocument()
    })
  })
})
