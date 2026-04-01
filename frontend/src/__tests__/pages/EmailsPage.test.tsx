import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/dashboard/emails',
  useSearchParams: () => new URLSearchParams(),
}))

import EmailsPage from '@/app/dashboard/emails/page'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={{ user: { ...mockUser, role: 'admin' as const }, isLoading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn() }}>
        <EmailsPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('EmailsPage', () => {
  it('shows loading skeletons initially', () => {
    server.use(http.get(`${API_URL}/emails/`, () => new Promise(() => {})))
    renderPage()
    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
  })

  it('shows empty state when no emails', async () => {
    server.use(http.get(`${API_URL}/emails/`, () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })))
    renderPage()
    await waitFor(() => { expect(screen.getByText('No generated emails yet')).toBeInTheDocument() })
  })

  it('renders grouped customer email data', async () => {
    server.use(http.get(`${API_URL}/emails/`, () => HttpResponse.json({
      count: 1, next: null, previous: null,
      results: [{ id: 'email-1', applicant_id: 1, applicant_name: 'Bob Jones', email_type: 'approval', subject: 'Approved', body_html: '<p>Approved</p>', passed_guardrails: true, guardrail_report: {}, created_at: '2024-06-01T00:00:00Z' }],
    })))
    renderPage()
    await waitFor(() => { expect(screen.getByText('Bob Jones')).toBeInTheDocument() })
  })
})
