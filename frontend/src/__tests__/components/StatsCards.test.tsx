import { render, screen } from '@testing-library/react'
import { StatsCards } from '@/components/dashboard/StatsCards'

describe('StatsCards', () => {
  const defaultProps = {
    totalApplications: 1500,
    approvalRate: 68.5,
    todayDecisions: { count: 17, p95LatencyMs: 4200 },
    llmSpend: { spentUsd: 1.23, capUsd: 5.0 },
  }

  it('renders all four stat cards', () => {
    render(<StatsCards {...defaultProps} />)

    expect(screen.getByText('Total Applications')).toBeInTheDocument()
    expect(screen.getByText('Approval Rate')).toBeInTheDocument()
    expect(screen.getByText("Today's Decisions")).toBeInTheDocument()
    expect(screen.getByText('LLM Spend')).toBeInTheDocument()
  })

  it('formats total applications with locale separator', () => {
    render(<StatsCards {...defaultProps} />)
    expect(screen.getByText('1,500')).toBeInTheDocument()
  })

  it('formats approval rate with one decimal', () => {
    render(<StatsCards {...defaultProps} />)
    expect(screen.getByText('68.5%')).toBeInTheDocument()
  })

  it('shows today’s decision count and p95 latency in seconds', () => {
    render(<StatsCards {...defaultProps} />)
    expect(screen.getByText('17')).toBeInTheDocument()
    // 4200ms → "p95 4.2s"
    expect(screen.getByText(/p95 4\.2s/i)).toBeInTheDocument()
  })

  it('shows LLM spend as dollars vs cap with progress', () => {
    render(<StatsCards {...defaultProps} />)
    expect(screen.getByText('$1.23')).toBeInTheDocument()
    expect(screen.getByText(/\/ \$5\.00 cap/i)).toBeInTheDocument()
    // Progress bar present
    expect(screen.getByRole('progressbar')).toBeInTheDocument()
  })

  it('renders fallback when p95 latency is null (no 24h decisions yet)', () => {
    render(
      <StatsCards
        {...defaultProps}
        todayDecisions={{ count: 0, p95LatencyMs: null }}
      />
    )
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.getByText(/no decisions yet/i)).toBeInTheDocument()
  })
})
