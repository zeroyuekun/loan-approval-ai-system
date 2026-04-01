import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser } from '@/test/mocks/handlers'
import { User, AgentRun } from '@/types'

const API_URL = 'http://localhost:8000/api/v1'

const mockRouterPush = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockRouterPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/dashboard/human-review',
  useSearchParams: () => new URLSearchParams(),
}))

import HumanReviewPage from '@/app/dashboard/human-review/page'

function makeEscalatedRun(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: 'run-1',
    application_id: 'app-12345678-abcd',
    applicant_name: 'Alice Smith',
    status: 'escalated',
    steps: [
      {
        step_name: 'human_review_required',
        status: 'completed',
        started_at: '2024-06-01T00:00:00Z',
        completed_at: '2024-06-01T00:00:01Z',
        result_summary: { reason: 'High bias score detected', review_category: 'bias_escalation' },
        error: null,
      },
    ],
    total_time_ms: 1500,
    error: '',
    created_at: '2024-06-01T00:00:00Z',
    updated_at: '2024-06-01T00:00:00Z',
    bias_reports: [
      {
        id: 'br-1',
        report_type: 'decision',
        bias_score: 75.5,
        deterministic_score: null,
        score_source: null,
        categories: ['age'],
        analysis: 'Potential age-based bias detected',
        flagged: true,
        requires_human_review: true,
        ai_review_approved: null,
        ai_review_reasoning: '',
        created_at: '2024-06-01T00:00:00Z',
      },
    ],
    next_best_offers: [],
    marketing_emails: [],
    ...overrides,
  }
}

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
        <HumanReviewPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('HumanReviewPage', () => {
  beforeEach(() => {
    mockRouterPush.mockReset()
  })

  it('renders "All clear" when no escalated runs', async () => {
    server.use(
      http.get(`${API_URL}/agents/runs/`, () => {
        return HttpResponse.json({
          count: 0,
          next: null,
          previous: null,
          results: [],
        })
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('All clear')).toBeInTheDocument()
    })
    expect(screen.getByText('No applications require human review at this time.')).toBeInTheDocument()
  })

  it('renders escalated runs in table with applicant name, reason, bias score', async () => {
    const run = makeEscalatedRun()
    server.use(
      http.get(`${API_URL}/agents/runs/`, () => {
        return HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [run],
        })
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Alice Smith')).toBeInTheDocument()
    })
    expect(screen.getByText('app-1234')).toBeInTheDocument()
    expect(screen.getByText('BIAS FLAG')).toBeInTheDocument()
    expect(screen.getByText('High bias score detected')).toBeInTheDocument()
    expect(screen.getByText('75.5')).toBeInTheDocument()
  })

  it('shows review modal when Review button clicked', async () => {
    const run = makeEscalatedRun()
    server.use(
      http.get(`${API_URL}/agents/runs/`, () => {
        return HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [run],
        })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Alice Smith')).toBeInTheDocument()
    })

    const reviewButton = screen.getByRole('button', { name: /review/i })
    await user.click(reviewButton)

    await waitFor(() => {
      expect(screen.getByText('Review Application')).toBeInTheDocument()
    })
    // The modal should show bias detection info and action buttons
    expect(screen.getByText('Bias Detection Flag')).toBeInTheDocument()
    expect(screen.getByText('Decision')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /deny/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /regenerate/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /submit review/i })).toBeInTheDocument()
  })

  it('handles pagination when multiple pages', async () => {
    const runs = Array.from({ length: 20 }, (_, i) =>
      makeEscalatedRun({
        id: `run-${i}`,
        application_id: `app-${String(i).padStart(8, '0')}-abcd`,
        applicant_name: `Applicant ${i}`,
      })
    )

    server.use(
      http.get(`${API_URL}/agents/runs/`, ({ request }) => {
        const url = new URL(request.url)
        const page = Number(url.searchParams.get('page') || '1')
        if (page === 1) {
          return HttpResponse.json({
            count: 25,
            next: `${API_URL}/agents/runs/?page=2`,
            previous: null,
            results: runs,
          })
        }
        return HttpResponse.json({
          count: 25,
          next: null,
          previous: `${API_URL}/agents/runs/?page=1`,
          results: [makeEscalatedRun({ id: 'run-extra', applicant_name: 'Extra Applicant' })],
        })
      }),
    )

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Applicant 0')).toBeInTheDocument()
    })

    // Pagination controls should be visible
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()
    expect(screen.getByText(/Showing 1 to 20 of 25/)).toBeInTheDocument()

    // Find the next page button - the one that is NOT disabled among pagination buttons
    const allButtons = screen.getAllByRole('button')
    // The "Previous" button is disabled on page 1, the "Next" button is enabled
    const nextPageBtn = allButtons.find(
      btn => !btn.hasAttribute('disabled') && btn.querySelector('svg') && !btn.textContent?.includes('Review')
    )
    expect(nextPageBtn).toBeTruthy()
    await user.click(nextPageBtn!)

    await waitFor(() => {
      expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
    })
  })

  it('shows error state on API failure', async () => {
    server.use(
      http.get(`${API_URL}/agents/runs/`, () => {
        return HttpResponse.json({ error: 'Server error' }, { status: 500 })
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Failed to load escalated applications. Please refresh the page.')).toBeInTheDocument()
    })
  })
})
