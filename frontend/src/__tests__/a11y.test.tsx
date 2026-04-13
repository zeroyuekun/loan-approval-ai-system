/**
 * Centralized accessibility smoke tests.
 *
 * Renders each major component in a representative state and runs axe-core
 * to detect WCAG violations. New components should be added here when
 * introduced. Component-specific behaviour tests live in their own files;
 * this file is the a11y safety net.
 *
 * Approach (single file vs per-test sprinkling): one centralized suite is
 * easier to audit, faster to iterate when triaging violations, and lets
 * us scope axe runs to representative renders rather than every assertion.
 */

import { render } from '@testing-library/react'
import { describe, it } from 'vitest'
import { expectNoAxeViolations } from '@/test/axe-helper'

import { BiasScoreBadge } from '@/components/emails/BiasScoreBadge'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import { StatsCards } from '@/components/dashboard/StatsCards'

describe('a11y smoke', () => {
  it('BiasScoreBadge — low score', async () => {
    const { container } = render(<BiasScoreBadge score={15} categories={[]} />)
    await expectNoAxeViolations(container)
  })

  it('BiasScoreBadge — high score with categories', async () => {
    const { container } = render(
      <BiasScoreBadge score={75} categories={['Gender bias', 'Age-based language']} />,
    )
    await expectNoAxeViolations(container)
  })

  it('ErrorBoundary — error state', async () => {
    function Boom(): JSX.Element {
      throw new Error('test')
    }
    const { container } = render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    await expectNoAxeViolations(container)
  })

  it('StatsCards — typical dashboard payload', async () => {
    const { container } = render(
      <StatsCards
        totalApplications={120}
        approvalRate={83}
        avgProcessingTime={45}
        activeModel="xgb-v1"
      />,
    )
    await expectNoAxeViolations(container)
  })
})
