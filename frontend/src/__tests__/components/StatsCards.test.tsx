import { render, screen } from '@testing-library/react'
import { StatsCards } from '@/components/dashboard/StatsCards'

describe('StatsCards', () => {
  const defaultProps = {
    totalApplications: 1500,
    approvalRate: 68.5,
    avgProcessingTime: '12.3s',
    activeModel: 'XGBoost v1',
  }

  it('renders all four stat cards', () => {
    render(<StatsCards {...defaultProps} />)

    expect(screen.getByText('Total Applications')).toBeInTheDocument()
    expect(screen.getByText('Approval Rate')).toBeInTheDocument()
    expect(screen.getByText('Avg Processing')).toBeInTheDocument()
    expect(screen.getByText('Active Model')).toBeInTheDocument()
  })

  it('formats total applications with locale separator', () => {
    render(<StatsCards {...defaultProps} />)

    expect(screen.getByText('1,500')).toBeInTheDocument()
  })

  it('formats approval rate with one decimal', () => {
    render(<StatsCards {...defaultProps} />)

    expect(screen.getByText('68.5%')).toBeInTheDocument()
  })

  it('displays processing time and model name', () => {
    render(<StatsCards {...defaultProps} />)

    expect(screen.getByText('12.3s')).toBeInTheDocument()
    expect(screen.getByText('XGBoost v1')).toBeInTheDocument()
  })
})
