import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useRequestDecisionReview } from '@/hooks/useDecisionReview'

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

it('exposes a mutation to request a review', () => {
  const { result } = renderHook(() => useRequestDecisionReview(), { wrapper })
  expect(typeof result.current.mutate).toBe('function')
})
