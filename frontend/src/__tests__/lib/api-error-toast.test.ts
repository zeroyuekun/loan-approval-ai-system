import { http, HttpResponse } from 'msw'
import { toast } from 'sonner'
import { server } from '@/test/mocks/server'
import api, { agentsApi, loansApi, mlApi, withNotFoundFallback } from '@/lib/api'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const API_URL = 'http://localhost:8000/api/v1'

describe('api error toasts', () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear()
  })

  it('does not toast an expected 404 that withNotFoundFallback turns into a fallback', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () =>
        HttpResponse.json({ detail: 'No active model' }, { status: 404 }),
      ),
    )

    const result = await withNotFoundFallback(async () => (await mlApi.getMetrics()).data, null)

    expect(result).toBeNull()
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('does not toast the 404 the agent-run poll gets before a run exists', async () => {
    server.use(
      http.get(`${API_URL}/agents/runs/loan-1/`, () =>
        HttpResponse.json({ detail: 'Not found.' }, { status: 404 }),
      ),
    )

    await expect(agentsApi.getRun('loan-1')).rejects.toMatchObject({ response: { status: 404 } })
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('still toasts a server error on a read', async () => {
    server.use(
      http.get(`${API_URL}/loans/`, () => HttpResponse.json({ detail: 'Server exploded' }, { status: 500 })),
    )

    await expect(api.get('/loans/')).rejects.toThrow()
    expect(toast.error).toHaveBeenCalledWith('Server exploded')
  })

  it('still toasts a 404 on a write, where no caller shows its own message', async () => {
    server.use(
      http.post(`${API_URL}/loans/decision-reviews/`, () =>
        HttpResponse.json({ detail: 'Application not found.' }, { status: 404 }),
      ),
    )

    await expect(api.post('/loans/decision-reviews/', {})).rejects.toThrow()
    expect(toast.error).toHaveBeenCalledWith('Application not found.')
  })

  it('still toasts an unexpected GET 404', async () => {
    server.use(
      http.get(`${API_URL}/loans/missing/`, () => HttpResponse.json({ detail: 'Not found.' }, { status: 404 })),
    )

    await expect(loansApi.get('missing')).rejects.toMatchObject({ response: { status: 404 } })
    expect(toast.error).toHaveBeenCalledWith('Not found.')
  })
})
