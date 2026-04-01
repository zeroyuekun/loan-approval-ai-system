import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'

const API_URL = 'http://localhost:8000/api/v1'

// We need to import a fresh api instance for each test to avoid shared state
// with the refreshPromise variable
async function getApi() {
  // Dynamic import to get the module
  const mod = await import('@/lib/api')
  return mod.default
}

describe('api interceptors', () => {
  it('injects X-CSRFToken header on POST requests when cookie exists', async () => {
    // Set a CSRF cookie
    document.cookie = 'csrftoken=test-csrf-token-abc123;path=/'

    let capturedHeaders: Record<string, string> = {}
    server.use(
      http.post(`${API_URL}/loans/`, ({ request }) => {
        capturedHeaders = Object.fromEntries(request.headers.entries())
        return HttpResponse.json({ id: 'loan-1' }, { status: 201 })
      })
    )

    const api = await getApi()
    await api.post('/loans/', { amount: 10000 })

    expect(capturedHeaders['x-csrftoken']).toBe('test-csrf-token-abc123')
  })

  it('retries with refresh on 401 and replays the original request', async () => {
    let callCount = 0

    server.use(
      http.get(`${API_URL}/loans/`, () => {
        callCount++
        if (callCount === 1) {
          return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
        }
        return HttpResponse.json({ count: 0, results: [] })
      }),
      http.post(`${API_URL}/auth/refresh/`, () => {
        return HttpResponse.json({ detail: 'Refreshed' })
      })
    )

    const api = await getApi()
    const response = await api.get('/loans/')

    expect(response.data).toEqual({ count: 0, results: [] })
    expect(callCount).toBe(2)
  })

  it('does not attempt refresh for auth-check paths (/auth/me/)', async () => {
    let refreshCalled = false

    server.use(
      http.get(`${API_URL}/auth/me/`, () => {
        return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      }),
      http.post(`${API_URL}/auth/refresh/`, () => {
        refreshCalled = true
        return HttpResponse.json({ detail: 'Refreshed' })
      })
    )

    const api = await getApi()
    await expect(api.get('/auth/me/')).rejects.toThrow()
    expect(refreshCalled).toBe(false)
  })

  it('propagates error when refresh itself fails', async () => {
    server.use(
      http.get(`${API_URL}/loans/`, () => {
        return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      }),
      http.post(`${API_URL}/auth/refresh/`, () => {
        return HttpResponse.json({ detail: 'Refresh token expired' }, { status: 401 })
      })
    )

    const api = await getApi()
    await expect(api.get('/loans/')).rejects.toThrow()
  })
})
