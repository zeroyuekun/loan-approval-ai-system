import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
})

// Request interceptor to add JWT token
api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

// Module-level variable to deduplicate concurrent refresh requests
let refreshPromise: Promise<string> | null = null

// Response interceptor for token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    const isRefreshRequest = originalRequest.url?.includes('/auth/refresh/')
    if (error.response?.status === 401 && !originalRequest._retry && !isRefreshRequest) {
      originalRequest._retry = true
      try {
        // Deduplicate: if a refresh is already in flight, reuse the same promise
        if (!refreshPromise) {
          refreshPromise = (async () => {
            const refreshToken = localStorage.getItem('refresh_token')
            if (!refreshToken) {
              throw new Error('No refresh token')
            }
            const { data } = await axios.post(`${API_URL}/auth/refresh/`, { refresh: refreshToken })
            localStorage.setItem('access_token', data.access)
            return data.access as string
          })()
        }
        const newToken = await refreshPromise
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return api(originalRequest)
      } catch {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('user')
        window.location.href = '/login'
        return Promise.reject(error)
      } finally {
        refreshPromise = null
      }
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
  getRuns: (params?: any) => api.get('/agents/runs/', { params }),
  getRun: (loanId: string) => api.get(`/agents/runs/${loanId}/`),
}

// Tasks
export const tasksApi = {
  getStatus: (taskId: string) => api.get(`/tasks/${taskId}/status/`),
}
