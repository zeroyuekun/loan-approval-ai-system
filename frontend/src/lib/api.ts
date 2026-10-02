import axios from 'axios'
import { toast } from 'sonner'
import { resetClientState } from '@/lib/clientState'
import { resolveApiUrl } from '@/lib/csp'
import { AdhocScoreFields, AdhocScoreResult } from '@/types'

// API parameter and payload types
interface PaginationParams {
  page?: number
  page_size?: number
  status?: string
  search?: string
  ordering?: string
  [key: string]: string | number | boolean | undefined
}

export interface RegisterPayload {
  username: string
  email: string
  password: string
  password2?: string
  first_name: string
  last_name: string
  role?: string
}

interface CustomerProfilePayload {
  date_of_birth?: string | null
  phone?: string
  address_line_1?: string
  address_line_2?: string
  suburb?: string
  state?: string
  postcode?: string
  employer_name?: string
  occupation?: string
  industry?: string
  employment_status?: string
  gross_annual_income?: number | null
  [key: string]: string | number | boolean | string[] | null | undefined
}

export interface LoanPayload {
  annual_income?: number
  credit_score?: number
  loan_amount?: number
  loan_term_months?: number
  debt_to_income?: number
  employment_length?: number
  purpose?: string
  home_ownership?: string
  has_cosigner?: boolean
  property_value?: number | null
  deposit_amount?: number | null
  monthly_expenses?: number | null
  number_of_dependants?: number
  employment_type?: string
  applicant_type?: string
  notes?: string
  [key: string]: string | number | boolean | null | undefined
}

// Production builds without NEXT_PUBLIC_API_URL use the same-origin /api/v1
// path rather than baking in localhost (see lib/csp.ts).
const API_URL = resolveApiUrl(process.env.NEXT_PUBLIC_API_URL, process.env.NODE_ENV)

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
  withCredentials: true, // Send HttpOnly cookies with every request
})

/**
 * Clear per-user client state and redirect to login. Called from the
 * response interceptor when a token refresh fails (interceptors run outside
 * React, so this cannot go through useAuth.logout()). The hard navigation
 * drops the in-memory React Query cache; resetClientState clears the rest.
 */
function clearAuthAndRedirect(): void {
  resetClientState()
  if (typeof window !== 'undefined') {
    window.location.assign('/login')
  }
}

// Helper to read the CSRF token from the csrftoken cookie
function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? match[1] : null
}

// Request interceptor to add CSRF token for mutating requests
api.interceptors.request.use((config) => {
  const method = (config.method || '').toLowerCase()
  if (['post', 'put', 'patch', 'delete'].includes(method)) {
    const csrfToken = getCsrfToken()
    if (csrfToken) {
      config.headers['X-CSRFToken'] = csrfToken
    }
  }
  return config
})

// Response interceptor for token refresh via cookies
let refreshPromise: Promise<void> | null = null

// Session-bootstrap paths (profile fetch on mount). A 401 here still gets one
// refresh attempt, so a reload after the access cookie expires is rescued by
// the refresh cookie. If that refresh fails the 401 propagates WITHOUT a hard
// redirect: useAuth sets user=null and the layout routes to /login, which
// avoids a reload loop on the login page itself.
const AUTH_CHECK_PATHS = ['/auth/me/', '/auth/me/profile/']

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    const isRefreshRequest = originalRequest.url?.includes('/auth/refresh/')
    const isAuthCheck = AUTH_CHECK_PATHS.some((p) => originalRequest.url?.includes(p))

    if (error.response?.status === 401 && !originalRequest._retry && !isRefreshRequest) {
      originalRequest._retry = true
      try {
        // Deduplicate: if a refresh is already in flight, reuse the same promise
        if (!refreshPromise) {
          // Cookie-based refresh — server reads refresh_token from HttpOnly cookie.
          // No inner try/catch: failures must propagate as rejections so that
          // parallel waiters see a rejection (not undefined) and do NOT retry
          // their original requests into a second 401 loop.
          refreshPromise = axios.post(`${API_URL}/auth/refresh/`, {}, { withCredentials: true }).then(() => undefined)
        }
        await refreshPromise
      } catch {
        // Refresh failed. For normal requests, clear auth state and redirect
        // to login so the user is not left on a blank/stuck page.
        if (!isAuthCheck) clearAuthAndRedirect()
        return Promise.reject(error)
      } finally {
        refreshPromise = null
      }
      // Replay outside the try: an error from the replayed request (a 404, a
      // second 401) is that request's own failure, not a failed refresh.
      return api(originalRequest)
    }
    if (error.response?.status === 401 && isAuthCheck) {
      return Promise.reject(error)
    }
    // Retry transient failures (429 Too Many Requests, 503 Service Unavailable)
    const retryableStatus = [429, 503]
    const retryCount = originalRequest._retryCount || 0
    if (retryableStatus.includes(error.response?.status) && retryCount < 2) {
      originalRequest._retryCount = retryCount + 1
      const delay = Math.pow(2, retryCount) * 1000 // 1s, 2s
      await new Promise((resolve) => setTimeout(resolve, delay))
      return api(originalRequest)
    }

    // Show toast for non-401 errors (401s handled by refresh logic)
    if (error.response?.status && error.response.status !== 401) {
      const message = error.response?.data?.detail
        || error.response?.data?.error
        || error.message
        || 'An unexpected error occurred'
      toast.error(message)
    }
    return Promise.reject(error)
  }
)

export default api

/**
 * Run `request`, resolving to `fallback` when the endpoint answers 404
 * (e.g. no active model has been trained yet). Any other error is rethrown.
 */
export async function withNotFoundFallback<T, F>(request: () => Promise<T>, fallback: F): Promise<T | F> {
  try {
    return await request()
  } catch (err) {
    if ((err as { response?: { status?: number } }).response?.status === 404) {
      return fallback
    }
    throw err
  }
}

// Auth
export const authApi = {
  login: (data: { username: string; password: string }) => api.post('/auth/login/', data),
  register: (data: RegisterPayload) => api.post('/auth/register/', data),
  getProfile: () => api.get('/auth/me/'),
  getCustomerProfile: () => api.get('/auth/me/profile/'),
  updateCustomerProfile: (data: CustomerProfilePayload) => api.patch('/auth/me/profile/', data),
  getCustomerDetail: (userId: number) => api.get(`/auth/customers/${userId}/profile/`),
  updateCustomerDetail: (userId: number, data: CustomerProfilePayload) => api.patch(`/auth/customers/${userId}/profile/`, data),
  listCustomers: (params?: PaginationParams) => api.get('/auth/customers/', { params }),
  getCustomerActivity: (userId: number) => api.get(`/auth/customers/${userId}/activity/`),
  getCsrfToken: () => api.get('/auth/csrf/'),
}

// Loans
export const loansApi = {
  list: (params?: PaginationParams) => api.get('/loans/', { params }),
  get: (id: string) => api.get(`/loans/${id}/`),
  create: (data: LoanPayload) => api.post('/loans/', data),
  update: (id: string, data: Partial<LoanPayload>) => api.patch(`/loans/${id}/`, data),
  delete: (id: string) => api.delete(`/loans/${id}/`),
  getDashboardStats: () => api.get('/loans/dashboard-stats/'),
}

// ML
export const mlApi = {
  predict: (loanId: string) => api.post(`/ml/predict/${loanId}/`),
  getMetrics: () => api.get('/ml/models/active/metrics/'),
  scoreApplicant: (fields: AdhocScoreFields) => api.post<AdhocScoreResult>('/ml/models/active/score/', fields),
  trainModel: (algorithm: string) => api.post('/ml/models/train/', { algorithm }),
  getModelCard: () => api.get('/ml/models/active/model-card/'),
  getDriftReports: (limit?: number) => api.get('/ml/models/active/drift-reports/', { params: { limit: limit || 12 } }),
}

// Email
export const emailApi = {
  list: (params?: PaginationParams) => api.get('/emails/', { params }),
  generate: (loanId: string) => api.post(`/emails/generate/${loanId}/`),
  get: (loanId: string) => api.get(`/emails/${loanId}/`),
  sendLatest: (loanId: string) => api.post(`/emails/send/${loanId}/`),
}

// Agents
export const agentsApi = {
  orchestrate: (loanId: string) => api.post(`/agents/orchestrate/${loanId}/`, null, { timeout: 60000 }),
  forceRerun: (loanId: string, reason?: string) =>
    api.post(`/agents/orchestrate/${loanId}/`, null, {
      timeout: 60000,
      params: { force: true, ...(reason && { reason }) },
    }),
  orchestrateAll: (recheck?: boolean) => api.post(`/agents/orchestrate-all/${recheck ? '?recheck=true' : ''}`, null, { timeout: 60000 }),
  getRuns: (params?: PaginationParams) => api.get('/agents/runs/', { params }),
  getRun: (loanId: string) => api.get(`/agents/runs/${loanId}/`),
  submitReview: (runId: string, data: { action: 'approve' | 'deny' | 'regenerate'; note?: string }) =>
    api.post(`/agents/review/${runId}/`, data),
}

// Audit
export const auditApi = {
  list: (params?: PaginationParams) => api.get('/loans/audit-logs/', { params }),
}

// Tasks
export const tasksApi = {
  getStatus: (taskId: string) => api.get(`/tasks/${taskId}/status/`),
}
