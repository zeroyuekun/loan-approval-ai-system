import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { useDashboardStats } from '@/hooks/useDashboardStats'

const API_URL = 'http://localhost:8000/api/v1'

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useDashboardStats', () => {
  it('returns stats payload on success', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () =>
        HttpResponse.json({
          total_applications: 42,
          approval_rate: 70.5,
          approved_count: 30,
          denied_count: 12,
          avg_processing_seconds: 2.4,
          decision_latency_p50_ms_24h: 1800,
          decision_latency_p95_ms_24h: 4200,
          decisions_24h_count: 17,
          llm_spend_today_usd: 1.23,
          llm_spend_cap_usd: 5.0,
          active_model: { name: 'xgb v3', auc: 0.87 },
          daily_volume: [],
          approval_trend: [],
          pipeline: { total: 0, completed: 0, failed: 0, escalated: 0, success_rate: 0 },
        })
      )
    )

    const { result } = renderHook(() => useDashboardStats(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.decisions_24h_count).toBe(17)
    expect(result.current.data?.llm_spend_today_usd).toBe(1.23)
    expect(result.current.data?.decision_latency_p95_ms_24h).toBe(4200)
  })

  it('surfaces error state on 500', async () => {
    server.use(
      http.get(`${API_URL}/loans/dashboard-stats/`, () =>
        new HttpResponse(null, { status: 500 })
      )
    )

    const { result } = renderHook(() => useDashboardStats(), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
