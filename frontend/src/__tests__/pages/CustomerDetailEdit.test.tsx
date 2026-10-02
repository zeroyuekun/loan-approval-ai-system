import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { useParams } from 'next/navigation'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser, mockCustomerUser, mockCustomerProfile } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import CustomerProfilePage from '@/app/dashboard/customers/[id]/page'

// Staff detail GET: the ID number keys carry the masked value.
const staffDetail = {
  ...mockCustomerProfile,
  user: mockCustomerUser,
  primary_id_number: '****3456',
  secondary_id_number: '****9012',
  date_of_birth: null,
  gross_annual_income: null,
  years_in_current_role: null,
  other_income: null,
  partner_annual_income: null,
  time_at_current_address_years: null,
}

function setup(detail: Record<string, unknown> = staffDetail) {
  const captured: { body: Record<string, unknown> | null } = { body: null }
  server.use(
    http.get(`${API_URL}/auth/customers/2/profile/`, () => HttpResponse.json(detail)),
    http.patch(`${API_URL}/auth/customers/2/profile/`, async ({ request }) => {
      captured.body = (await request.json()) as Record<string, unknown>
      return HttpResponse.json(detail)
    }),
    http.get(`${API_URL}/auth/customers/2/activity/`, () => HttpResponse.json({ emails: [], agent_runs: [] })),
    http.get(`${API_URL}/loans/`, () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider
        value={{ user: mockUser, isLoading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn() }}
      >
        <CustomerProfilePage />
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
  return captured
}

describe('Customer detail page admin edit', () => {
  beforeEach(() => {
    vi.mocked(useParams).mockReturnValue({ id: '2' })
  })

  it('sends only the changed field, leaving empty server values untouched', async () => {
    const captured = setup()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /edit profile/i }))
    const phone = screen.getByDisplayValue('0412345678')
    await user.clear(phone)
    await user.type(phone, '0499999999')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body).toEqual({ phone: '0499999999' })
  })

  it('sends null for a cleared number field instead of zero', async () => {
    const captured = setup({ ...staffDetail, years_in_current_role: 7.5 })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /edit profile/i }))
    await user.clear(screen.getByDisplayValue('7.5'))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body).toEqual({ years_in_current_role: null })
  })

  it('sends 0 for a cleared field the server stores as NOT NULL', async () => {
    // estimated_property_value is DecimalField(default=0): null would be a 400.
    const captured = setup({ ...staffDetail, estimated_property_value: 650000 })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /edit profile/i }))
    await user.clear(screen.getByDisplayValue('650000'))
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(captured.body).not.toBeNull())
    expect(captured.body).toEqual({ estimated_property_value: 0 })
  })
})
