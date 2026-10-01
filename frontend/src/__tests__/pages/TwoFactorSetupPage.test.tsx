import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import TwoFactorSetupPage from '@/app/dashboard/two-factor/page'

const API_URL = 'http://localhost:8000/api/v1'

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TwoFactorSetupPage />
    </QueryClientProvider>,
  )
}

describe('TwoFactorSetupPage', () => {
  it('says so when two-factor authentication is already on', async () => {
    server.use(http.get(`${API_URL}/auth/2fa/status/`, () => HttpResponse.json({ enabled: true, required: true })))
    renderPage()
    expect(await screen.findByText(/two-factor authentication is on/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /set up authenticator/i })).not.toBeInTheDocument()
  })

  it('enrols: shows the QR code and secret, then confirms with a code', async () => {
    let verifiedWith: unknown = null
    server.use(
      http.get(`${API_URL}/auth/2fa/status/`, () => HttpResponse.json({ enabled: false, required: true })),
      http.post(`${API_URL}/auth/2fa/setup/`, () =>
        HttpResponse.json({
          provisioning_uri: 'otpauth://totp/AussieLoanAI:officer1?secret=JBSWY3DPEHPK3PXP&issuer=AussieLoanAI',
          qr_code_base64: 'iVBORw0KGgo=',
          detail: 'Scan the QR code',
        }),
      ),
      http.post(`${API_URL}/auth/2fa/verify/`, async ({ request }) => {
        verifiedWith = await request.json()
        return HttpResponse.json({ detail: '2FA verified successfully.', confirmed: true })
      }),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /set up authenticator/i }))

    const qr = await screen.findByAltText(/qr code/i)
    expect(qr).toHaveAttribute('src', 'data:image/png;base64,iVBORw0KGgo=')
    expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()

    await user.type(screen.getByLabelText('6-digit code'), '123456')
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    expect(await screen.findByText(/two-factor authentication is on/i)).toBeInTheDocument()
    expect(verifiedWith).toEqual({ token: '123456' })
  })

  it('shows the server message when the code is rejected', async () => {
    server.use(
      http.get(`${API_URL}/auth/2fa/status/`, () => HttpResponse.json({ enabled: false, required: true })),
      http.post(`${API_URL}/auth/2fa/setup/`, () =>
        HttpResponse.json({ provisioning_uri: 'otpauth://totp/x?secret=ABC', qr_code_base64: null, detail: '' }),
      ),
      http.post(`${API_URL}/auth/2fa/verify/`, () =>
        HttpResponse.json({ detail: 'Invalid or expired token.' }, { status: 400 }),
      ),
    )
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: /set up authenticator/i }))
    await user.type(await screen.findByLabelText('6-digit code'), '000000')
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid or expired token.')).toBeInTheDocument()
    })
  })
})
