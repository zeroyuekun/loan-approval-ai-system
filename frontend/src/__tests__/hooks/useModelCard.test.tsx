import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { useModelCard } from '@/hooks/useModelCard'
import { server } from '@/test/mocks/server'

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

describe('useModelCard', () => {
  it('fetches model card successfully', async () => {
    const { result } = renderHook(() => useModelCard(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data?.model_details.algorithm).toBe('xgboost')
    expect(result.current.data?.performance_metrics.auc_roc).toBe(0.87)
    expect(result.current.data?.governance.status).toBe('active')
  })

  it('returns null on 404', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/model-card/`, () => {
        return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
      }),
    )

    const { result } = renderHook(() => useModelCard(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    expect(result.current.data).toBeNull()
  })

  it('throws on non-404 errors', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/model-card/`, () => {
        return HttpResponse.json({ error: 'Server error' }, { status: 500 })
      }),
    )

    const { result } = renderHook(() => useModelCard(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })
})
