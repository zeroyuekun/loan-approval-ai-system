/**
 * Type augmentation for vitest-axe 0.1.0 with vitest 4.
 *
 * vitest-axe 0.1.0 uses the legacy `namespace Vi` augmentation pattern which
 * does not work with vitest 4. This file uses the correct `declare module
 * 'vitest'` pattern (same approach as @testing-library/jest-dom) so that
 * `expect(axeResults).toHaveNoViolations()` is properly typed.
 */
import 'vitest'
import type { AxeResults } from 'axe-core'

declare module 'vitest' {
  interface Assertion<T = any> {
    toHaveNoViolations(): void
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void
  }
}
