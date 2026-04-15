import axe from 'axe-core'
import { expect } from 'vitest'

/**
 * Run axe-core over the given container and assert no serious or critical
 * violations. Used by component-level Vitest tests to approximate the
 * Playwright accessibility suite at the unit level.
 *
 * We filter on serious+critical only because some WCAG-AA checks
 * (e.g. colour contrast) rely on rendered CSS that jsdom does not
 * compute; those surface as incomplete/minor and should not fail
 * component tests. Full-page colour-contrast checks live in the
 * Playwright suite at e2e/accessibility.spec.ts.
 */
export async function expectNoAxeViolations(container: Element): Promise<void> {
  const results = await axe.run(container, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
    resultTypes: ['violations'],
  })

  const critical = results.violations.filter(
    (v) => v.impact === 'critical' || v.impact === 'serious',
  )

  expect(critical, JSON.stringify(critical, null, 2)).toEqual([])
}
