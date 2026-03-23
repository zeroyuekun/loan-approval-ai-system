import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GuardrailLogDisplay } from '@/components/emails/GuardrailLogDisplay'
import { GuardrailCheck } from '@/types'

const mockChecks: GuardrailCheck[] = [
  { check_name: 'Tone Check', passed: true, details: 'Professional tone detected' },
  { check_name: 'Compliance Check', passed: true, details: 'All regulatory language present' },
  { check_name: 'PII Check', passed: false, details: 'Potential PII leakage found' },
]

describe('GuardrailLogDisplay', () => {
  it('renders correct pass/fail counts', () => {
    render(<GuardrailLogDisplay checks={mockChecks} />)

    // 2 of 3 passed
    expect(screen.getByText('2/3 passed')).toBeInTheDocument()
  })

  it('expands and collapses check details on click', async () => {
    const user = userEvent.setup()
    render(<GuardrailLogDisplay checks={mockChecks} />)

    // Details should not be visible initially
    expect(screen.queryByText('Professional tone detected')).not.toBeInTheDocument()

    // Click to expand the Tone Check
    await user.click(screen.getByText('Tone Check'))
    expect(screen.getByText('Professional tone detected')).toBeInTheDocument()

    // Click again to collapse
    await user.click(screen.getByText('Tone Check'))
    expect(screen.queryByText('Professional tone detected')).not.toBeInTheDocument()
  })

  it('displays quality score when present on first check', () => {
    const checksWithScore = [
      { check_name: 'Tone Check', passed: true, details: 'Good', quality_score: 92 },
      { check_name: 'PII Check', passed: true, details: 'Clean' },
    ] as (GuardrailCheck & { quality_score?: number })[]

    render(<GuardrailLogDisplay checks={checksWithScore as GuardrailCheck[]} />)

    expect(screen.getByText('92/100')).toBeInTheDocument()
  })
})
