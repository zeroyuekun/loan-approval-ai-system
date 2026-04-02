import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { useDriftReports } from '@/hooks/useDriftReports'
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

describe('useDriftReports', () => {
  it('fetches drift reports successfully', async () => {
    const { result } = renderHook(() => useDriftReports(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data).toHaveLength(1)
    expect(result.current.data?.[0].psi_score).toBe(0.08)
    expect(result.current.data?.[0].drift_detected).toBe(false)
  })

  it('returns empty array on 404', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/drift-reports/`, () => {
        return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
      }),
    )

    const { result } = renderHook(() => useDriftReports(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    expect(result.current.data).toEqual([])
  })

  it('throws on non-404 errors', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/drift-reports/`, () => {
        return HttpResponse.json({ error: 'Server error' }, { status: 500 })
      }),
    )

    const { result } = renderHook(() => useDriftReports(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })

  it('passes limit parameter', async () => {
    let capturedUrl = ''
    server.use(
      http.get(`${API_URL}/ml/models/active/drift-reports/`, ({ request }) => {
        capturedUrl = request.url
        return HttpResponse.json([])
      }),
    )

    const { result } = renderHook(() => useDriftReports(6), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    expect(capturedUrl).toContain('limit=6')
  })
})
