import type { ErrorEvent } from '@sentry/nextjs'
import { scrubEvent, sentryBaseOptions } from '@/lib/sentryScrub'

function event(): ErrorEvent {
  return {
    type: undefined,
    message: 'boom',
    request: {
      url: 'https://app.example.com/apply/new',
      method: 'POST',
      data: { annual_income: 120000, notes: 'private' },
      cookies: { access_token: 'secret' },
      query_string: 'token=abc',
      headers: {
        'User-Agent': 'jest',
        Cookie: 'access_token=secret',
        Authorization: 'Bearer secret',
        'X-CSRFToken': 'csrf',
      },
    },
    user: { id: '7', email: 'jane@example.com', username: 'jane', ip_address: '1.2.3.4' },
  }
}

describe('scrubEvent', () => {
  it('drops request bodies, cookies, query strings and credential headers', () => {
    const out = scrubEvent(event())!
    expect(out.request?.data).toBeUndefined()
    expect(out.request?.cookies).toBeUndefined()
    expect(out.request?.query_string).toBeUndefined()
    expect(out.request?.headers).toEqual({ 'User-Agent': 'jest' })
    // The page URL and method stay useful for debugging
    expect(out.request?.url).toBe('https://app.example.com/apply/new')
    expect(out.request?.method).toBe('POST')
  })

  it('keeps only the opaque user id', () => {
    const out = scrubEvent(event())!
    expect(out.user).toEqual({ id: '7' })
  })

  it('copes with events that carry no request or user', () => {
    expect(scrubEvent({ type: undefined, message: 'x' })).toEqual({ type: undefined, message: 'x' })
  })
})

describe('sentryBaseOptions', () => {
  it('never sends default PII and scrubs every event', () => {
    const opts = sentryBaseOptions('https://k@o1.ingest.sentry.io/2')
    expect(opts.sendDefaultPii).toBe(false)
    expect(opts.dsn).toBe('https://k@o1.ingest.sentry.io/2')
    expect(opts.beforeSend).toBe(scrubEvent)
  })
})
