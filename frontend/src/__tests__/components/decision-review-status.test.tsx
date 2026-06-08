import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DenialExplanationPanel } from '@/components/applications/DenialExplanationPanel'
import { DecisionReviewStatus } from '@/components/applications/DecisionReviewStatus'

vi.mock('@/hooks/useDecisionReview', () => ({
  useDecisionReview: () => ({ data: null }),
  useRequestDecisionReview: () => ({ mutate: vi.fn(), isPending: false }),
}))

const baseProps = {
  denialReasons: [{ code: 'R06', reason: 'Credit score below minimum', feature: 'credit_score' }],
  counterfactuals: [],
  reapplicationGuidance: null,
  creditScore: 500,
}

describe('DenialExplanationPanel ADM + review', () => {
  it('shows the ADM disclosure line and a request-review CTA', () => {
    render(
      <DenialExplanationPanel
        {...baseProps}
        applicationId="app-1"
        admDisclosure={{
          mode: 'solely_automated',
          summary: 'Declined by our automated credit-decision model.',
          info_used: ['Income'],
          human_review_right: true,
          review_request_path: '/api/v1/loans/decision-reviews/',
        }}
      />
    )
    expect(screen.getByText(/automated credit-decision model/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /request a human review/i })).toBeInTheDocument()
  })

  it('DecisionReviewStatus renders no request form on approved/review screens (allowRequest=false, no prior review)', () => {
    // The backend only accepts reviews on declined applications, so the
    // approved/review screens must not offer a form that 400s on submit.
    render(<DecisionReviewStatus applicationId="app-1" allowRequest={false} />)
    expect(screen.queryByRole('button', { name: /request a human review/i })).not.toBeInTheDocument()
  })
})
