import { QueryClient } from '@tanstack/react-query'
import { DRAFT_STORAGE_KEY, TRAINING_STORAGE_KEY, resetClientState } from '@/lib/clientState'

describe('resetClientState', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('clears every per-user client store', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['customerProfile'], { address_line_1: '1 Secret St' })
    sessionStorage.setItem('user', JSON.stringify({ role: 'customer', username: 'alice' }))
    document.cookie = 'user_role=customer;path=/'
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify({ savedAt: Date.now(), data: { annual_income: 1 } }))
    localStorage.setItem(TRAINING_STORAGE_KEY, JSON.stringify({ taskId: 't', startedAt: Date.now() }))
    localStorage.setItem('unrelated_key', 'keep')

    resetClientState(queryClient)

    expect(queryClient.getQueryData(['customerProfile'])).toBeUndefined()
    expect(sessionStorage.getItem('user')).toBeNull()
    expect(document.cookie).not.toContain('user_role=customer')
    expect(localStorage.getItem(DRAFT_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(TRAINING_STORAGE_KEY)).toBeNull()
    // Only app-owned keys are removed
    expect(localStorage.getItem('unrelated_key')).toBe('keep')
  })

  it('still clears storage when no query client is available', () => {
    localStorage.setItem(DRAFT_STORAGE_KEY, 'x')
    resetClientState()
    expect(localStorage.getItem(DRAFT_STORAGE_KEY)).toBeNull()
  })
})
