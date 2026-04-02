import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { useDashboardStats } from '@/hooks/useDashboardStats'
import { server } from '@/test/mocks/server'
import { mockDashboardStats } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return Wrapper
}

describe('useDashboardStats', () => {
  it('fetches dashboard stats successfully', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () => {
        return HttpResponse.json(mockDashboardStats)
      }),
    )

    const { result } = renderHook(() => useDashboardStats(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
      expect(result.current.data).not.toBeUndefined()
    })

    const data = result.current.data!
    expect(data.total_applications).toBe(150)
    expect(data.approval_rate).toBe(68.5)
    expect(data.active_model?.name).toBe('xgboost_v1')
    expect(data.pipeline.success_rate).toBe(86.7)
  })

  it('returns loading state initially', () => {
    const { result } = renderHook(() => useDashboardStats(), {
      wrapper: createWrapper(),
    })

    expect(result.current.isLoading).toBe(true)
    expect(result.current.data).toBeUndefined()
  })

  it('handles server errors', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () => {
        return HttpResponse.json({ error: 'Server error' }, { status: 500 })
      }),
    )

    const { result } = renderHook(() => useDashboardStats(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })
})
