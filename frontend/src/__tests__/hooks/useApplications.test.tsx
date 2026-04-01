import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { useApplications, useApplication, useCreateApplication, useUpdateApplication } from '@/hooks/useApplications'
import { server } from '@/test/mocks/server'
import { mockLoanApplication } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return Wrapper
}

describe('useApplications', () => {
  it('fetches paginated applications', async () => {
    const { result } = renderHook(() => useApplications(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data?.count).toBe(1)
    expect(result.current.data?.results[0].id).toBe('loan-1')
  })

  it('passes filter params to API', async () => {
    server.use(
      http.get(`${API_URL}/loans/`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('status')).toBe('approved')
        expect(url.searchParams.get('page')).toBe('2')
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
    )

    const { result } = renderHook(
      () => useApplications({ status: 'approved', page: 2 }),
      { wrapper: createWrapper() },
    )

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
  })

  it('handles server error', async () => {
    server.use(
      http.get(`${API_URL}/loans/`, () => {
        return HttpResponse.json({ error: 'Server error' }, { status: 500 })
      }),
    )

    const { result } = renderHook(() => useApplications(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })
})

describe('useApplication', () => {
  it('fetches a single application by id', async () => {
    const { result } = renderHook(() => useApplication('loan-1'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data?.id).toBe('loan-1')
    expect(result.current.data?.credit_score).toBe(750)
  })

  it('does not fetch when id is empty', () => {
    const { result } = renderHook(() => useApplication(''), {
      wrapper: createWrapper(),
    })

    expect(result.current.data).toBeUndefined()
    expect(result.current.isFetching).toBe(false)
  })

  it('handles 404', async () => {
    server.use(
      http.get(`${API_URL}/loans/:id/`, () => {
        return HttpResponse.json({ error: 'Not found' }, { status: 404 })
      }),
    )

    const { result } = renderHook(() => useApplication('nonexistent'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })
})

describe('useCreateApplication', () => {
  it('creates an application and returns data', async () => {
    const { result } = renderHook(() => useCreateApplication(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate({
        annual_income: 85000,
        credit_score: 750,
        loan_amount: 25000,
        loan_term_months: 36,
        purpose: 'personal',
      })
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    expect(result.current.data?.id).toBe('loan-1')
  })

  it('handles validation error', async () => {
    server.use(
      http.post(`${API_URL}/loans/`, () => {
        return HttpResponse.json(
          { loan_amount: ['Ensure this value is greater than 0.'] },
          { status: 400 },
        )
      }),
    )

    const { result } = renderHook(() => useCreateApplication(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate({ loan_amount: -100 })
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })
})

describe('useUpdateApplication', () => {
  it('updates an application', async () => {
    const updatedApp = { ...mockLoanApplication, notes: 'Updated note' }
    server.use(
      http.patch(`${API_URL}/loans/:id/`, () => {
        return HttpResponse.json(updatedApp)
      }),
    )

    const { result } = renderHook(() => useUpdateApplication(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate({ id: 'loan-1', data: { notes: 'Updated note' } })
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
  })
})
