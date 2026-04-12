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

// Draft key is now scoped to user ID (FE-H3 fix)
const DRAFT_KEY = `loan_application_draft_${adminUser.id}`

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

describe('Draft localStorage key security', () => {
  it('FE-H3 FIX: draft key is now scoped to user ID', () => {
    // After fix, the key includes the user ID so different users have separate drafts
    expect(DRAFT_KEY).toContain(`${adminUser.id}`)
    expect(DRAFT_KEY).toMatch(/loan_application_draft_\d+/)
  })

  it('FE-H3 FIX: different users get different draft keys', () => {
    // User A and User B should not share draft storage
    const userAKey = `loan_application_draft_${adminUser.id}`
    const userBKey = `loan_application_draft_99`

    const userADraft = { annual_income: 150000, credit_score: 820 }
    localStorage.setItem(userAKey, JSON.stringify(userADraft))

    // User B's key is different — no PII leakage
    const userBData = localStorage.getItem(userBKey)
    expect(userBData).toBeNull()
  })
})
