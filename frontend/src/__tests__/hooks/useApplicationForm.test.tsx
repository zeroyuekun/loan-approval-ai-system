import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthContext } from '@/lib/auth'
import { useApplicationForm, STEP_LABELS } from '@/hooks/useApplicationForm'
import { User } from '@/types'

const mockRouterPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockRouterPush,
    replace: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}))

const mockMutateAsync = vi.fn()
vi.mock('@/hooks/useApplications', () => ({
  useCreateApplication: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
    isError: false,
  }),
}))

const adminUser: User = {
  id: 1,
  username: 'admin',
  email: 'admin@example.com',
  role: 'admin',
  first_name: 'Admin',
  last_name: 'User',
}

function createWrapper(user: User = adminUser) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthContext.Provider value={{
          user,
          isLoading: false,
          login: vi.fn(),
          register: vi.fn(),
          logout: vi.fn(),
        }}>
          {children}
        </AuthContext.Provider>
      </QueryClientProvider>
    )
  }
  return Wrapper
}

const DRAFT_KEY = 'loan_application_draft'

describe('useApplicationForm', () => {
  beforeEach(() => {
    mockMutateAsync.mockReset()
    mockRouterPush.mockReset()
    localStorage.clear()
  })

  it('starts at step 1 with correct total steps', () => {
    const { result } = renderHook(() => useApplicationForm(), {
      wrapper: createWrapper(),
    })

    expect(result.current.step).toBe(1)
    expect(result.current.totalSteps).toBe(STEP_LABELS.length)
  })

  it('restores draft from localStorage', () => {
    const draft = { annual_income: 120000, credit_score: 800 }
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))

    const { result } = renderHook(() => useApplicationForm(), {
      wrapper: createWrapper(),
    })

    const watched = result.current.watch()
    expect(watched.annual_income).toBe(120000)
    expect(watched.credit_score).toBe(800)
  })

  it('persists form changes to localStorage', async () => {
    const { result } = renderHook(() => useApplicationForm(), {
      wrapper: createWrapper(),
    })

    act(() => {
      result.current.form.setValue('annual_income', 95000)
    })

    await waitFor(() => {
      const stored = localStorage.getItem(DRAFT_KEY)
      expect(stored).toBeTruthy()
      expect(JSON.parse(stored!).annual_income).toBe(95000)
    })
  })

  it('clears draft on successful submission', async () => {
    mockMutateAsync.mockResolvedValue({ id: 'new-123' })
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ annual_income: 50000 }))

    const { result } = renderHook(() => useApplicationForm(), {
      wrapper: createWrapper(),
    })

    // Fill required fields so validation passes
    act(() => {
      result.current.form.setValue('annual_income', 85000)
      result.current.form.setValue('credit_score', 750)
      result.current.form.setValue('loan_amount', 25000)
    })

    await act(async () => {
      result.current.onSubmit()
    })

    await waitFor(() => {
      expect(localStorage.getItem(DRAFT_KEY)).toBeNull()
    })
  })

  it('navigates forward and backward through steps', async () => {
    const { result } = renderHook(() => useApplicationForm(), {
      wrapper: createWrapper(),
    })

    expect(result.current.step).toBe(1)

    // Step 1 fields have defaults, so validation should pass
    await act(async () => {
      await result.current.goNext()
    })
    expect(result.current.step).toBe(2)

    act(() => {
      result.current.goPrev()
    })
    expect(result.current.step).toBe(1)
  })

  it('does not go below step 1', () => {
    const { result } = renderHook(() => useApplicationForm(), {
      wrapper: createWrapper(),
    })

    act(() => {
      result.current.goPrev()
    })
    expect(result.current.step).toBe(1)
  })

  it('handles corrupted localStorage draft gracefully', () => {
    localStorage.setItem(DRAFT_KEY, 'not-valid-json{{{')

    const { result } = renderHook(() => useApplicationForm(), {
      wrapper: createWrapper(),
    })

    // Should still initialize with defaults, not crash
    expect(result.current.step).toBe(1)
    expect(result.current.watch().applicant_type).toBe('single')
  })
})

describe('useApplicationForm — localStorage debounce', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('writes to localStorage at most once per 500ms window', () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const { result } = renderHook(() => useApplicationForm(), {
      wrapper: createWrapper(),
    })

    act(() => {
      for (let i = 0; i < 10; i++) {
        result.current.form.setValue('annual_income', 1000 + i)
      }
    })

    act(() => {
      vi.advanceTimersByTime(100)
    })
    const callsBefore = setItemSpy.mock.calls.filter(
      (c) => c[0] === DRAFT_KEY,
    ).length
    expect(callsBefore).toBeLessThanOrEqual(1)

    act(() => {
      vi.advanceTimersByTime(500)
    })
    const callsAfter = setItemSpy.mock.calls.filter(
      (c) => c[0] === DRAFT_KEY,
    ).length
    expect(callsAfter).toBe(1)

    setItemSpy.mockRestore()
  })
})
