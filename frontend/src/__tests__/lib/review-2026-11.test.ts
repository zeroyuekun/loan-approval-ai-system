import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { isTerminalTaskStatus, MAX_TASK_POLL_MS, taskPollingExpired } from '@/lib/polling'
import { sanitizeEmailHtml, stripPositioning } from '@/components/emails/EmailPreview'

const API_URL = 'http://localhost:8000/api/v1'

describe('task polling bounds', () => {
  it('treats REVOKED like SUCCESS and FAILURE', () => {
    expect(isTerminalTaskStatus('SUCCESS')).toBe(true)
    expect(isTerminalTaskStatus('FAILURE')).toBe(true)
    expect(isTerminalTaskStatus('REVOKED')).toBe(true)
    expect(isTerminalTaskStatus('PENDING')).toBe(false)
    expect(isTerminalTaskStatus(undefined)).toBe(false)
  })

  it('expires after the polling cap', () => {
    const start = 1_000_000
    expect(taskPollingExpired(start, start + MAX_TASK_POLL_MS)).toBe(false)
    expect(taskPollingExpired(start, start + MAX_TASK_POLL_MS + 1)).toBe(true)
  })
})

describe('email preview sanitising', () => {
  it('drops positioning declarations and keeps the rest', () => {
    expect(stripPositioning('position:fixed; z-index:9; color:red; TOP: 0')).toBe('color:red')
  })

  it('removes overlay styles from sanitised email HTML', () => {
    const out = sanitizeEmailHtml('<div style="position:fixed;inset:0;z-index:99;color:red">x</div>')
    expect(out).toContain('color:red')
    expect(out).not.toMatch(/position|z-index|inset/)
  })
})

describe('transient-error retries', () => {
  it('does not resend a POST after a 503', async () => {
    let calls = 0
    server.use(
      http.post(`${API_URL}/loans/`, () => {
        calls++
        return HttpResponse.json({ detail: 'busy' }, { status: 503 })
      })
    )
    const api = (await import('@/lib/api')).default
    await expect(api.post('/loans/', {})).rejects.toBeTruthy()
    expect(calls).toBe(1)
  })

  it('still retries a GET after a 503', async () => {
    let calls = 0
    server.use(
      http.get(`${API_URL}/loans/`, () => {
        calls++
        return calls === 1
          ? HttpResponse.json({ detail: 'busy' }, { status: 503 })
          : HttpResponse.json({ results: [] })
      })
    )
    const api = (await import('@/lib/api')).default
    const resp = await api.get('/loans/')
    expect(resp.status).toBe(200)
    expect(calls).toBe(2)
  }, 10_000)
})
