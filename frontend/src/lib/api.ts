import axios from 'axios'
import { toast } from 'sonner'

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
  register: (data: any) => api.post('/auth/register/', data),
  getProfile: () => api.get('/auth/me/'),
  getCustomerProfile: () => api.get('/auth/me/profile/'),
  updateCustomerProfile: (data: any) => api.patch('/auth/me/profile/', data),
  getCustomerDetail: (userId: number) => api.get(`/auth/customers/${userId}/profile/`),
  updateCustomerDetail: (userId: number, data: any) => api.patch(`/auth/customers/${userId}/profile/`, data),
  listCustomers: (params?: any) => api.get('/auth/customers/', { params }),
  getCustomerActivity: (userId: number) => api.get(`/auth/customers/${userId}/activity/`),
  getCsrfToken: () => api.get('/auth/csrf/'),
}

// Loans
export const loansApi = {
  list: (params?: any) => api.get('/loans/', { params }),
  get: (id: string) => api.get(`/loans/${id}/`),
  create: (data: any) => api.post('/loans/', data),
  update: (id: string, data: any) => api.patch(`/loans/${id}/`, data),
  delete: (id: string) => api.delete(`/loans/${id}/`),
}

// ML
export const mlApi = {
  predict: (loanId: string) => api.post(`/ml/predict/${loanId}/`),
  getMetrics: () => api.get('/ml/models/active/metrics/'),
  trainModel: (algorithm: string) => api.post('/ml/models/train/', { algorithm }),
}

// Email
export const emailApi = {
  list: (params?: any) => api.get('/emails/', { params }),
  generate: (loanId: string) => api.post(`/emails/generate/${loanId}/`),
  get: (loanId: string) => api.get(`/emails/${loanId}/`),
}

// Agents
export const agentsApi = {
  orchestrate: (loanId: string) => api.post(`/agents/orchestrate/${loanId}/`),
  orchestrateAll: (recheck?: boolean) => api.post(`/agents/orchestrate-all/${recheck ? '?recheck=true' : ''}`),
  getRuns: (params?: any) => api.get('/agents/runs/', { params }),
  getRun: (loanId: string) => api.get(`/agents/runs/${loanId}/`),
  submitReview: (runId: string, data: { action: 'approve' | 'deny' | 'regenerate'; note?: string }) =>
    api.post(`/agents/review/${runId}/`, data),
}

// Audit
export const auditApi = {
  list: (params?: any) => api.get('/loans/audit-logs/', { params }),
}

// Tasks
export const tasksApi = {
  getStatus: (taskId: string) => api.get(`/tasks/${taskId}/status/`),
}
