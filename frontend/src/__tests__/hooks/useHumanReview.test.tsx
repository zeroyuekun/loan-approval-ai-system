import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { useEscalatedRuns, useSubmitReview } from '@/hooks/useHumanReview'
import { server } from '@/test/mocks/server'

const API_URL = 'http://localhost:8500/api/v1'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return Wrapper
}

const mockEscalatedRun = {
  id: 'run-esc-1',
  application_id: 'loan-456',
  applicant_name: 'Jane Smith',
  status: 'escalated',
  steps: [
    { step_name: 'human_review_required', status: 'completed', result_summary: { review_category: 'bias_escalation', reason: 'Severe bias detected (score 72)' } },
  ],
  total_time_ms: 3000,
  error: '',
  bias_reports: [
    {
      id: 'br-1',
      report_type: 'decision',
      bias_score: 72,
      deterministic_score: 65,
      score_source: 'deterministic',
      categories: ['age'],
      analysis: 'Age-related bias detected',
      flagged: true,
      requires_human_review: true,
      ai_review_approved: false,
      ai_review_reasoning: '',
      created_at: '2026-03-27T10:00:00Z',
    },
  ],
  next_best_offers: [],
  marketing_emails: [],
  created_at: '2026-03-27T10:00:00Z',
  updated_at: '2026-03-27T10:01:00Z',
}

describe('useEscalatedRuns', () => {
  it('fetches escalated runs with status=escalated', async () => {
    server.use(
      http.get(`${API_URL}/agents/runs/`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('status')).toBe('escalated')
        return HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [mockEscalatedRun],
        })
      }),
    )

    const { result } = renderHook(() => useEscalatedRuns(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data?.count).toBe(1)
    expect(result.current.data?.results[0].id).toBe('run-esc-1')
    expect(result.current.data?.results[0].status).toBe('escalated')
  })

  it('passes page parameter', async () => {
    server.use(
      http.get(`${API_URL}/agents/runs/`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('page')).toBe('2')
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
    )

    const { result } = renderHook(() => useEscalatedRuns({ page: 2 }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
  })

  it('returns empty results when no escalated runs', async () => {
    server.use(
      http.get(`${API_URL}/agents/runs/`, () => {
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
    )

    const { result } = renderHook(() => useEscalatedRuns(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data?.results).toHaveLength(0)
  })

  it('handles server error', async () => {
    server.use(
      http.get(`${API_URL}/agents/runs/`, () => {
        return HttpResponse.json({ error: 'Internal error' }, { status: 500 })
      }),
    )

    const { result } = renderHook(() => useEscalatedRuns(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })
})

describe('useSubmitReview', () => {
  it('submits approve action', async () => {
    server.use(
      http.post(`${API_URL}/agents/review/:runId/`, async ({ request }) => {
        const body = await request.json() as Record<string, unknown>
        expect(body.action).toBe('approve')
        return HttpResponse.json({ status: 'review_approved_pipeline_resuming', action: 'approve' })
      }),
    )

    const { result } = renderHook(() => useSubmitReview(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate({ runId: 'run-esc-1', action: 'approve' })
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
  })

  it('submits deny action with note', async () => {
    server.use(
      http.post(`${API_URL}/agents/review/:runId/`, async ({ request }) => {
        const body = await request.json() as Record<string, unknown>
        expect(body.action).toBe('deny')
        expect(body.note).toBe('Confirmed bias issue')
        return HttpResponse.json({ status: 'application_denied_by_reviewer', action: 'deny' })
      }),
    )

    const { result } = renderHook(() => useSubmitReview(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate({ runId: 'run-esc-1', action: 'deny', note: 'Confirmed bias issue' })
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
  })

  it('submits regenerate action', async () => {
    server.use(
      http.post(`${API_URL}/agents/review/:runId/`, async ({ request }) => {
        const body = await request.json() as Record<string, unknown>
        expect(body.action).toBe('regenerate')
        return HttpResponse.json({ status: 'regeneration_queued', action: 'regenerate' })
      }),
    )

    const { result } = renderHook(() => useSubmitReview(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate({ runId: 'run-esc-1', action: 'regenerate' })
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
  })

  it('handles submission failure', async () => {
    server.use(
      http.post(`${API_URL}/agents/review/:runId/`, () => {
        return HttpResponse.json({ error: 'Agent run is not escalated' }, { status: 409 })
      }),
    )

    const { result } = renderHook(() => useSubmitReview(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate({ runId: 'run-esc-1', action: 'approve' })
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })
})
