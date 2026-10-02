/**
 * Owner of the per-user client state lifecycle.
 *
 * Everything the browser keeps for the signed-in user lives in one of:
 *   - sessionStorage `user` + the `user_role` cookie (lib/session.ts)
 *   - the React Query cache (keys are not user-scoped, e.g. ['customerProfile'])
 *   - localStorage keys listed in USER_LOCAL_STORAGE_KEYS
 * Both sign-out paths (useAuth.logout and the api.ts refresh-failure redirect)
 * call resetClientState, so the next person on the same browser sees none of it.
 * A new localStorage key holding user data must be added to the list below.
 */
import type { QueryClient } from '@tanstack/react-query'
import { clearSession } from '@/lib/session'

/** Loan application draft (income, credit score, notes) — useApplicationForm. */
export const DRAFT_STORAGE_KEY = 'loan_application_draft'
/** In-flight model training task — useMetrics. */
export const TRAINING_STORAGE_KEY = 'aussieloanai_training_task'

const USER_LOCAL_STORAGE_KEYS = [DRAFT_STORAGE_KEY, TRAINING_STORAGE_KEY]

function removeLocal(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // Storage unavailable (private mode / SSR) — nothing to clear.
  }
}

export function resetClientState(queryClient?: QueryClient): void {
  clearSession()
  if (typeof localStorage !== 'undefined') {
    USER_LOCAL_STORAGE_KEYS.forEach(removeLocal)
  }
  queryClient?.clear()
}

/**
 * Drop an application draft that belongs to someone other than `username`.
 * Covers the case where the previous user closed the tab without signing out,
 * so logout never ran. Drafts saved before owners were recorded are dropped too.
 */
export function clearForeignDraft(username: string): void {
  if (typeof localStorage === 'undefined') return
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_KEY)
    if (!raw) return
    const owner = (JSON.parse(raw) as { owner?: unknown }).owner
    if (owner !== username) removeLocal(DRAFT_STORAGE_KEY)
  } catch {
    removeLocal(DRAFT_STORAGE_KEY)
  }
}
