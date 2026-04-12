import { readFileSync } from 'fs'
import { join } from 'path'

describe('CI Deploy Safety', () => {
  const ciConfig = readFileSync(
    join(__dirname, '../../../.github/workflows/ci.yml'),
    'utf-8',
  )

  it('deploy job should use explicit success checks, not absence-of-failure', () => {
    // FE-H4 FIX: deploy condition now uses result == 'success' for each job
    // instead of !contains(needs.*.result, 'failure').
    const hasUnsafePattern = ciConfig.includes('!contains(needs.')
    expect(hasUnsafePattern).toBe(false)
  })

  it('deploy job should not use always() with negation pattern', () => {
    // FE-H4 FIX: always() && !contains(...) anti-pattern removed.
    const hasAlwaysWithNegation = /always\(\)\s*&&.*!contains/.test(ciConfig)
    expect(hasAlwaysWithNegation).toBe(false)
  })
})
