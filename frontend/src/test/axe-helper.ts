import { axe } from 'vitest-axe'
import { expect } from 'vitest'

/**
 * Run axe-core against a rendered container and assert no a11y violations.
 *
 * The toHaveNoViolations matcher is registered in setup.ts via expect.extend.
 *
 * Usage at the end of any rendering test:
 *   const { container } = render(<MyComponent />)
 *   await expectNoAxeViolations(container)
 */
export async function expectNoAxeViolations(container: HTMLElement): Promise<void> {
  const results = await axe(container)
  // @ts-expect-error - matcher extension provides toHaveNoViolations
  expect(results).toHaveNoViolations()
}
