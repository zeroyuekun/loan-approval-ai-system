const { init } = vi.hoisted(() => ({ init: vi.fn() }))
vi.mock('@sentry/nextjs', () => ({
  init,
  captureRouterTransitionStart: vi.fn(),
  captureRequestError: vi.fn(),
}))

describe('Sentry wiring (Next 16 instrumentation files)', () => {
  const originalDsn = process.env.NEXT_PUBLIC_SENTRY_DSN

  beforeEach(() => {
    vi.resetModules()
    init.mockReset()
  })
  afterEach(() => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = originalDsn
  })

  it('instrumentation-client initialises Sentry without PII when a DSN is set', async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'https://k@o1.ingest.sentry.io/2'
    const mod = await import('@/instrumentation-client')
    expect(init).toHaveBeenCalledTimes(1)
    const opts = init.mock.calls[0][0]
    expect(opts.dsn).toBe('https://k@o1.ingest.sentry.io/2')
    expect(opts.sendDefaultPii).toBe(false)
    expect(typeof opts.beforeSend).toBe('function')
    expect(mod.onRouterTransitionStart).toBeDefined()
  })

  it('instrumentation-client does nothing without a DSN', async () => {
    delete process.env.NEXT_PUBLIC_SENTRY_DSN
    await import('@/instrumentation-client')
    expect(init).not.toHaveBeenCalled()
  })

  it('instrumentation register() loads the server config on the Node runtime', async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'https://k@o1.ingest.sentry.io/2'
    const prevRuntime = process.env.NEXT_RUNTIME
    process.env.NEXT_RUNTIME = 'nodejs'
    try {
      const mod = await import('@/instrumentation')
      await mod.register()
      expect(init).toHaveBeenCalledTimes(1)
      expect(init.mock.calls[0][0].sendDefaultPii).toBe(false)
      expect(mod.onRequestError).toBeDefined()
    } finally {
      process.env.NEXT_RUNTIME = prevRuntime
    }
  })
})
