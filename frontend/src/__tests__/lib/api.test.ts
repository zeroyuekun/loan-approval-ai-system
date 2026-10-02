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

  it('refreshes once and replays /auth/me/ when the access cookie expired (session bootstrap)', async () => {
    // A reload after the 60-min access cookie expired must use the 7-day
    // refresh cookie instead of logging the user out.
    let meCalls = 0
    let refreshCalls = 0
    server.use(
      http.get(`${API_URL}/auth/me/`, () => {
        meCalls++
        if (meCalls === 1) return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
        return HttpResponse.json({ id: 1, username: 'alice', role: 'customer' })
      }),
      http.post(`${API_URL}/auth/refresh/`, () => {
        refreshCalls++
        return HttpResponse.json({ detail: 'Refreshed' })
      })
    )

    const api = await getApi()
    const response = await api.get('/auth/me/')

    expect(response.data.username).toBe('alice')
    expect(refreshCalls).toBe(1)
    expect(meCalls).toBe(2)
  })

  it('rejects /auth/me/ without a hard redirect when the bootstrap refresh fails', async () => {
    // No refresh cookie (never logged in): one refresh attempt, then reject so
    // useAuth resolves to user=null and the layout redirects via the router.
    // A window.location.assign here would reload /login in a loop.
    const assignSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign: assignSpy },
      writable: true,
      configurable: true,
    })
    let refreshCalls = 0
    server.use(
      http.get(`${API_URL}/auth/me/`, () => HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })),
      http.post(`${API_URL}/auth/refresh/`, () => {
        refreshCalls++
        return HttpResponse.json({ detail: 'No refresh token' }, { status: 401 })
      })
    )

    const api = await getApi()
    await expect(api.get('/auth/me/')).rejects.toMatchObject({ response: { status: 401 } })
    expect(refreshCalls).toBe(1)
    expect(assignSpy).not.toHaveBeenCalled()
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

  it('clears sessionStorage user and calls window.location.assign(/login) when refresh fails', async () => {
    // Seed sessionStorage with a user so we can verify it is cleared
    sessionStorage.setItem('user', JSON.stringify({ role: 'admin', username: 'admin' }))
    localStorage.setItem('loan_application_draft', JSON.stringify({ savedAt: Date.now(), data: {} }))

    // jsdom does not support real navigation; spy on window.location.assign.
    // Object.defineProperty is needed because jsdom's location is not fully writable.
    const assignSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign: assignSpy },
      writable: true,
      configurable: true,
    })

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

    // sessionStorage 'user' key must be removed
    expect(sessionStorage.getItem('user')).toBeNull()
    // per-user drafts must not survive into the next session
    expect(localStorage.getItem('loan_application_draft')).toBeNull()
    // window.location.assign('/login') must have been called
    expect(assignSpy).toHaveBeenCalledWith('/login')
  })
  describe('staff 2FA enrolment (403 code 2fa_enrolment_required)', () => {
    function stubLocation(pathname: string) {
      const assignSpy = vi.fn()
      Object.defineProperty(window, 'location', {
        value: { ...window.location, pathname, assign: assignSpy },
        writable: true,
        configurable: true,
      })
      return assignSpy
    }

    function enrolmentRequired() {
      return HttpResponse.json(
        { detail: 'Two-factor authentication must be set up', code: '2fa_enrolment_required' },
        { status: 403 },
      )
    }

    it('sends the user to the enrolment page', async () => {
      const assignSpy = stubLocation('/dashboard')
      server.use(http.get(`${API_URL}/loans/`, enrolmentRequired))

      const api = await getApi()
      await expect(api.get('/loans/')).rejects.toThrow()

      expect(assignSpy).toHaveBeenCalledWith('/dashboard/two-factor')
    })

    it('does not redirect again when already on the enrolment page', async () => {
      const assignSpy = stubLocation('/dashboard/two-factor')
      server.use(http.get(`${API_URL}/loans/`, enrolmentRequired))

      const api = await getApi()
      await expect(api.get('/loans/')).rejects.toThrow()

      expect(assignSpy).not.toHaveBeenCalled()
    })

    it('leaves other 403s alone', async () => {
      const assignSpy = stubLocation('/dashboard')
      server.use(
        http.get(`${API_URL}/loans/`, () => HttpResponse.json({ detail: 'Forbidden' }, { status: 403 })),
      )

      const api = await getApi()
      await expect(api.get('/loans/')).rejects.toThrow()

      expect(assignSpy).not.toHaveBeenCalled()
    })
  })
})
