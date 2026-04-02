import { render, screen, fireEvent } from '@testing-library/react'
import { RepaymentCalculator } from '@/components/applications/RepaymentCalculator'

describe('RepaymentCalculator', () => {
  it('renders with default values', () => {
    render(<RepaymentCalculator />)

    expect(screen.getByText('Repayment Estimator')).toBeInTheDocument()
    expect(screen.getByText('360 months')).toBeInTheDocument()
    expect(screen.getByText('6.50% p.a.')).toBeInTheDocument()
  })

  it('renders with custom props', () => {
    render(
      <RepaymentCalculator
        loanAmount={500000}
        loanTermMonths={240}
        interestRate={5.5}
      />,
    )

    expect(screen.getByText('240 months')).toBeInTheDocument()
    expect(screen.getByText('5.50% p.a.')).toBeInTheDocument()
  })

  it('calculates monthly repayment', () => {
    render(
      <RepaymentCalculator
        loanAmount={300000}
        loanTermMonths={360}
        interestRate={6.5}
      />,
    )

    expect(screen.getByText('Monthly Repayment')).toBeInTheDocument()
    // Monthly repayment for $300k at 6.5% over 30yr is ~$1,896
    const repaymentEl = screen.getByText('Monthly Repayment').closest('div')
    expect(repaymentEl?.textContent).toMatch(/\$1,89[0-9]/)
  })

  it('shows stress test buttons', () => {
    render(<RepaymentCalculator />)

    expect(screen.getByText('Base')).toBeInTheDocument()
    expect(screen.getByText('+1%')).toBeInTheDocument()
    expect(screen.getByText('+2%')).toBeInTheDocument()
    expect(screen.getByText('+3%')).toBeInTheDocument()
  })

  it('updates rate when stress test button clicked', () => {
    render(<RepaymentCalculator interestRate={6.5} />)

    fireEvent.click(screen.getByText('+3%'))

    expect(screen.getByText('9.50% p.a.')).toBeInTheDocument()
  })

  it('shows increase from stress test', () => {
    render(<RepaymentCalculator interestRate={6.5} />)

    fireEvent.click(screen.getByText('+3%'))

    expect(screen.getByText(/Increase from stress test/)).toBeInTheDocument()
  })

  it('displays APRA serviceability note', () => {
    render(<RepaymentCalculator />)

    expect(screen.getByText(/APRA serviceability/)).toBeInTheDocument()
  })

  it('displays comparison rate', () => {
    render(<RepaymentCalculator interestRate={6.5} />)

    expect(screen.getByText(/Comparison.*% p\.a\.\*/)).toBeInTheDocument()
  })
})
