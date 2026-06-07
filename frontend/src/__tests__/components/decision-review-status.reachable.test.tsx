import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DecisionReviewStatus } from '@/components/applications/DecisionReviewStatus'

vi.mock('@/hooks/useDecisionReview', () => ({
  useDecisionReview: () => ({
    data: { id: 'r1', application: 'app-1', status: 'overturned' },
  }),
  useRequestDecisionReview: () => ({ mutate: vi.fn(), isPending: false }),
}))

describe('DecisionReviewStatus reachability', () => {
  it('shows the overturned outcome even when the app is approved', () => {
    render(<DecisionReviewStatus applicationId="app-1" />)
    expect(
      screen.getByText(/decision overturned, your application was approved/i),
    ).toBeInTheDocument()
  })
})
