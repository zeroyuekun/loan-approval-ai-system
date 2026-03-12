import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
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

// Response interceptor for token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true
      try {
        const refreshToken = localStorage.getItem('refresh_token')
        const { data } = await axios.post(`${API_URL}/auth/refresh/`, { refresh: refreshToken })
        localStorage.setItem('access_token', data.access)
        originalRequest.headers.Authorization = `Bearer ${data.access}`
        return api(originalRequest)
      } catch {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        window.location.href = '/login'
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
}

// Loans
export const loansApi = {
  list: (params?: any) => api.get('/loans/', { params }),
  get: (id: string) => api.get(`/loans/${id}/`),
  create: (data: any) => api.post('/loans/', data),
  update: (id: string, data: any) => api.patch(`/loans/${id}/`, data),
}

// ML
export const mlApi = {
  predict: (loanId: string) => api.post(`/ml/predict/${loanId}/`),
  getMetrics: () => api.get('/ml/models/active/metrics/'),
  trainModel: (algorithm: string) => api.post('/ml/models/train/', { algorithm }),
}

// Email
export const emailApi = {
  generate: (loanId: string) => api.post(`/emails/generate/${loanId}/`),
  get: (loanId: string) => api.get(`/emails/${loanId}/`),
}

// Agents
export const agentsApi = {
  orchestrate: (loanId: string) => api.post(`/agents/orchestrate/${loanId}/`),
  getRun: (loanId: string) => api.get(`/agents/runs/${loanId}/`),
}

// Tasks
export const tasksApi = {
  getStatus: (taskId: string) => api.get(`/tasks/${taskId}/status/`),
}
