import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { useAgentRun, useTaskStatus } from '@/hooks/useAgentStatus'
import { server } from '@/test/mocks/server'

const API_URL = 'http://localhost:8500/api/v1'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return Wrapper
}

const mockCompletedRun = {
  id: 'run-1',
  application_id: 'loan-123',
  status: 'completed',
  steps: [{ step_name: 'ml_prediction', status: 'completed' }],
  total_time_ms: 5000,
  error: '',
  created_at: '2025-01-15T10:00:00Z',
  updated_at: '2025-01-15T10:01:00Z',
  bias_reports: [],
  next_best_offers: [],
  marketing_emails: [],
}

describe('useAgentRun', () => {
  it('fetches agent run for a loan', async () => {
    server.use(
      http.get(`${API_URL}/agents/runs/:loanId/`, () => {
        return HttpResponse.json(mockCompletedRun)
      }),
    )

    const { result } = renderHook(() => useAgentRun('loan-123'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data?.id).toBe('run-1')
    expect(result.current.data?.status).toBe('completed')
  })

  it('does not fetch when loanId is empty', () => {
    const { result } = renderHook(() => useAgentRun(''), {
      wrapper: createWrapper(),
    })

    expect(result.current.data).toBeUndefined()
    expect(result.current.isFetching).toBe(false)
  })

  it('returns error state on 404', async () => {
    server.use(
      http.get(`${API_URL}/agents/runs/:loanId/`, () => {
        return HttpResponse.json({ error: 'Not found' }, { status: 404 })
      }),
    )

    const { result } = renderHook(() => useAgentRun('nonexistent'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })
})

describe('useTaskStatus', () => {
  it('fetches task status', async () => {
    server.use(
      http.get(`${API_URL}/tasks/:taskId/status/`, () => {
        return HttpResponse.json({
          task_id: 'task-abc',
          status: 'SUCCESS',
          result: { agent_run_id: 'run-1' },
        })
      }),
    )

    const { result } = renderHook(() => useTaskStatus('task-abc'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data?.status).toBe('SUCCESS')
  })

  it('does not fetch when disabled', () => {
    const { result } = renderHook(
      () => useTaskStatus('task-abc', { enabled: false }),
      { wrapper: createWrapper() },
    )

    expect(result.current.data).toBeUndefined()
    expect(result.current.isFetching).toBe(false)
  })

  it('does not fetch with empty taskId', () => {
    const { result } = renderHook(() => useTaskStatus(''), {
      wrapper: createWrapper(),
    })

    expect(result.current.data).toBeUndefined()
    expect(result.current.isFetching).toBe(false)
  })
})
