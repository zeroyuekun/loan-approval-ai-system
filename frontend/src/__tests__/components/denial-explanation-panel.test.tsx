import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { DenialExplanationPanel } from '@/components/applications/DenialExplanationPanel'

const mockDenialReasons = [
  { code: 'D001', reason: 'Debt-to-income ratio exceeds threshold', feature: 'debt_to_income' },
  { code: 'D002', reason: 'Insufficient employment history', feature: 'employment_length' },
]

const mockCounterfactuals = [
  {
    changes: { debt_to_income: -0.15 },
    statement: 'If your debt-to-income ratio were 15% lower, the outcome may have been different.',
  },
  {
    changes: { employment_length: 2 },
    statement: 'If you had 2 more years of employment history, the outcome may have been different.',
  },
]

const mockReapplicationGuidance = {
  improvement_targets: [
    { feature: 'debt_to_income', current_value: '0.55', target_value: '0.40', description: 'Lower DTI' },
  ],
  estimated_review_months: 6,
  message: 'Consider reapplying after addressing these areas.',
}

const defaultProps = {
  denialReasons: mockDenialReasons,
  counterfactuals: mockCounterfactuals,
  reapplicationGuidance: mockReapplicationGuidance,
  creditScore: 500,
}

describe('DenialExplanationPanel', () => {
  it('renders 3 cards with correct headings', () => {
    render(<DenialExplanationPanel {...defaultProps} />)

    expect(
      screen.getByText("Why we couldn\u0027t approve your application")
    ).toBeInTheDocument()
    expect(screen.getByText('Try this and reapply')).toBeInTheDocument()
    expect(
      screen.getByText('Improving your profile for the future')
    ).toBeInTheDocument()
  })

  it('renders denial reason text', () => {
    render(<DenialExplanationPanel {...defaultProps} />)

    expect(screen.getByText('D001')).toBeInTheDocument()
    expect(
      screen.getByText('Debt-to-income ratio exceeds threshold')
    ).toBeInTheDocument()
    expect(screen.getByText('D002')).toBeInTheDocument()
    expect(
      screen.getByText('Insufficient employment history')
    ).toBeInTheDocument()
  })

  it('renders counterfactual statements', () => {
    render(<DenialExplanationPanel {...defaultProps} />)

    expect(
      screen.getByText(
        'If your debt-to-income ratio were 15% lower, the outcome may have been different.'
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'If you had 2 more years of employment history, the outcome may have been different.'
      )
    ).toBeInTheDocument()
  })

  it('renders credit score with Equifax band', () => {
    render(<DenialExplanationPanel {...defaultProps} creditScore={500} />)

    expect(screen.getByText(/500/)).toBeInTheDocument()
    expect(screen.getByText(/Average/)).toBeInTheDocument()
  })

  it('renders "Talk to a specialist" CTA', () => {
    render(<DenialExplanationPanel {...defaultProps} />)

    const cta = screen.getByRole('link', { name: /Talk to a specialist/i })
    expect(cta).toBeInTheDocument()
    expect(cta).toHaveAttribute('href', '/rights')
  })

  it('renders AFCA link', () => {
    render(<DenialExplanationPanel {...defaultProps} />)

    const afcaLink = screen.getByRole('link', { name: /AFCA/i })
    expect(afcaLink).toBeInTheDocument()
    expect(afcaLink).toHaveAttribute('href', '/rights')
  })

  it('has no axe violations', async () => {
    const { container } = render(<DenialExplanationPanel {...defaultProps} />)
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })

  it('returns null when denialReasons is empty', () => {
    const { container } = render(
      <DenialExplanationPanel
        denialReasons={[]}
        counterfactuals={mockCounterfactuals}
        reapplicationGuidance={mockReapplicationGuidance}
        creditScore={500}
      />
    )
    expect(container.innerHTML).toBe('')
  })

  it('hides card 2 when counterfactuals array is empty', () => {
    render(
      <DenialExplanationPanel
        denialReasons={mockDenialReasons}
        counterfactuals={[]}
        reapplicationGuidance={mockReapplicationGuidance}
        creditScore={null}
      />
    )

    expect(
      screen.getByText("Why we couldn\u0027t approve your application")
    ).toBeInTheDocument()
    expect(screen.queryByText('Try this and reapply')).not.toBeInTheDocument()
    expect(
      screen.getByText('Improving your profile for the future')
    ).toBeInTheDocument()
  })

  it('renders correct Equifax band for different scores', () => {
    const { rerender } = render(
      <DenialExplanationPanel {...defaultProps} creditScore={400} />
    )
    expect(screen.getByText(/Below Average/)).toBeInTheDocument()

    rerender(<DenialExplanationPanel {...defaultProps} creditScore={700} />)
    expect(screen.getByText(/Good/)).toBeInTheDocument()

    rerender(<DenialExplanationPanel {...defaultProps} creditScore={800} />)
    expect(screen.getByText(/Very Good/)).toBeInTheDocument()

    rerender(<DenialExplanationPanel {...defaultProps} creditScore={900} />)
    expect(screen.getByText(/Excellent/)).toBeInTheDocument()
  })
})
