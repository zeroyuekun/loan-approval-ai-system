import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import { useDecisionReview, useRequestDecisionReview } from '@/hooks/useDecisionReview'

const get = vi.fn()
vi.mock('@/lib/api', () => ({ default: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

it('exposes a mutation to request a review', () => {
  const { result } = renderHook(() => useRequestDecisionReview(), { wrapper })
  expect(typeof result.current.mutate).toBe('function')
})

it('fetches reviews filtered by application id and returns the single match', async () => {
  get.mockResolvedValueOnce({
    data: { results: [{ id: 'r1', application: 'app-1', status: 'overturned' }] },
  })
  const { result } = renderHook(() => useDecisionReview('app-1'), { wrapper })
  await waitFor(() => expect(result.current.data).not.toBeUndefined())
  expect(get).toHaveBeenCalledWith('/loans/decision-reviews/', { params: { application: 'app-1' } })
  expect(result.current.data?.status).toBe('overturned')
})
