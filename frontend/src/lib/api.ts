import axios from 'axios'
import { toast } from 'sonner'

// API parameter and payload types
interface PaginationParams {
  page?: number
  page_size?: number
  status?: string
  search?: string
  ordering?: string
  [key: string]: string | number | boolean | undefined
}

interface RegisterPayload {
  username: string
  email: string
  password: string
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

interface LoanPayload {
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

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8500/api/v1'

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
  withCredentials: true, // Send HttpOnly cookies with every request
})

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

// Paths where a 401 is expected and should NOT trigger a refresh/redirect cycle
const AUTH_CHECK_PATHS = ['/auth/me/', '/auth/me/profile/']

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    const isRefreshRequest = originalRequest.url?.includes('/auth/refresh/')
    const isAuthCheck = AUTH_CHECK_PATHS.some((p) => originalRequest.url?.includes(p))

    // For auth-check requests (profile fetch on mount), just let the 401 propagate
    // so useAuth can set user=null and redirect via React Router, not a hard reload
    if (error.response?.status === 401 && isAuthCheck) {
      return Promise.reject(error)
    }

    if (error.response?.status === 401 && !originalRequest._retry && !isRefreshRequest) {
      originalRequest._retry = true
      try {
        // Deduplicate: if a refresh is already in flight, reuse the same promise
        if (!refreshPromise) {
          refreshPromise = (async () => {
            // Cookie-based refresh — server reads refresh_token from HttpOnly cookie
            await axios.post(`${API_URL}/auth/refresh/`, {}, { withCredentials: true })
          })()
        }
        await refreshPromise
        return api(originalRequest)
      } catch {
        // Refresh failed — let the error propagate; useAuth handles the redirect
        return Promise.reject(error)
      } finally {
        refreshPromise = null
      }
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
  downloadDecisionLetter: (id: string) =>
    api.get(`/loans/${id}/decision-letter/`, { responseType: 'blob' }),
}

// ML
export const mlApi = {
  predict: (loanId: string) => api.post(`/ml/predict/${loanId}/`),
  getMetrics: () => api.get('/ml/models/active/metrics/'),
  trainModel: (algorithm: string) => api.post('/ml/models/train/', { algorithm }),
}

// Email
export const emailApi = {
  list: (params?: PaginationParams) => api.get('/emails/', { params }),
  generate: (loanId: string) => api.post(`/emails/generate/${loanId}/`),
  get: (loanId: string) => api.get(`/emails/${loanId}/`),
}

// Agents
export const agentsApi = {
  orchestrate: (loanId: string) => api.post(`/agents/orchestrate/${loanId}/?force=true`),
  orchestrateAll: (recheck?: boolean) => api.post(`/agents/orchestrate-all/${recheck ? '?recheck=true' : ''}`),
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
