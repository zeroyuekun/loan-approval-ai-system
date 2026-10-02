import type { ComponentType } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser, mockCustomerProfile } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

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
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import DashboardProfilePage from '@/app/dashboard/profile/page'
import ApplyProfilePage from '@/app/apply/profile/page'
import EditProfilePage from '@/app/apply/profile/edit/page'

// The real API: ID numbers are write-only, so GET returns only the masked form.
const serverProfile = {
  ...mockCustomerProfile,
  primary_id_number_masked: '****3456',
  secondary_id_number_masked: '****9012',
}

function renderPage(Page: ComponentType) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider
        value={{
          user: { ...mockUser, role: 'customer' as const, first_name: 'Jane', last_name: 'Doe' },
          isLoading: false,
          login: vi.fn(),
          register: vi.fn(),
          logout: vi.fn(),
        }}
      >
        <Page />
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

function capturePatch() {
  const captured: { body: Record<string, unknown> | null } = { body: null }
  server.use(
    http.get(`${API_URL}/auth/me/profile/`, () => HttpResponse.json(serverProfile)),
    http.patch(`${API_URL}/auth/me/profile/`, async ({ request }) => {
      captured.body = (await request.json()) as Record<string, unknown>
      return HttpResponse.json(serverProfile)
    }),
  )
  return captured
}

describe.each([
  ['dashboard profile', DashboardProfilePage, /save changes/i],
  ['apply profile', ApplyProfilePage, /save & continue/i],
])('%s page ID numbers', (_name, Page, saveLabel) => {
  it('does not send ID numbers the user did not type, so saving keeps the stored IDs', async () => {
    const captured = capturePatch()
    const user = userEvent.setup()
    renderPage(Page)

    const phone = await screen.findByDisplayValue('0412345678')
    await user.clear(phone)
    await user.type(phone, '0499999999')
    await user.click(screen.getByRole('button', { name: saveLabel }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body).toHaveProperty('phone', '0499999999')
    expect(captured.body).not.toHaveProperty('primary_id_number')
    expect(captured.body).not.toHaveProperty('secondary_id_number')
  })

  it('shows the masked stored ID as a placeholder and sends a newly typed ID number', async () => {
    const captured = capturePatch()
    const user = userEvent.setup()
    renderPage(Page)

    const primary = await screen.findByPlaceholderText('****3456')
    expect(screen.getByPlaceholderText('****9012')).toBeInTheDocument()
    await user.type(primary, 'DL998877')
    await user.click(screen.getByRole('button', { name: saveLabel }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body).toHaveProperty('primary_id_number', 'DL998877')
    expect(captured.body).not.toHaveProperty('secondary_id_number')
  })

  it('sends only the fields the user changed, so empty server values are not rewritten', async () => {
    const captured = capturePatch()
    server.use(
      http.get(`${API_URL}/auth/me/profile/`, () =>
        HttpResponse.json({
          ...serverProfile,
          date_of_birth: null,
          gross_annual_income: null,
          years_in_current_role: null,
        }),
      ),
    )
    const user = userEvent.setup()
    renderPage(Page)

    const phone = await screen.findByDisplayValue('0412345678')
    await user.clear(phone)
    await user.type(phone, '0499999999')
    await user.click(screen.getByRole('button', { name: saveLabel }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body).toEqual({ phone: '0499999999' })
  })

  it('sends null, not an empty string, for a cleared number field', async () => {
    const captured = capturePatch()
    const user = userEvent.setup()
    renderPage(Page)

    await screen.findByDisplayValue('0412345678')
    await user.clear(screen.getByLabelText(/gross annual income/i))
    await user.click(screen.getByRole('button', { name: saveLabel }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body).toEqual({ gross_annual_income: null })
  })
})

describe('apply profile edit page', () => {
  it('sends only the changed field', async () => {
    const captured = capturePatch()
    const user = userEvent.setup()
    renderPage(EditProfilePage)

    const phone = await screen.findByDisplayValue('0412345678')
    await user.clear(phone)
    await user.type(phone, '0499999999')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body).toEqual({ phone: '0499999999' })
  })

  it('sends null, not an empty string, for a cleared number field', async () => {
    const captured = capturePatch()
    const user = userEvent.setup()
    renderPage(EditProfilePage)

    await screen.findByDisplayValue('0412345678')
    await user.clear(screen.getByLabelText(/gross annual income/i))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body).toEqual({ gross_annual_income: null })
  })
})
