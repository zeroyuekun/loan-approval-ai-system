import { render, screen } from '@testing-library/react'
import { ApplicationTable } from '@/components/applications/ApplicationTable'
import { mockLoanApplication } from '@/test/mocks/handlers'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

describe('ApplicationTable', () => {
  const defaultProps = {
    applications: [mockLoanApplication],
    isLoading: false,
    totalCount: 1,
    page: 1,
    onPageChange: vi.fn(),
  }

  it('renders table headers', () => {
    render(<ApplicationTable {...defaultProps} />)

    expect(screen.getByText('ID')).toBeInTheDocument()
    expect(screen.getByText('Applicant')).toBeInTheDocument()
    expect(screen.getByText('Amount')).toBeInTheDocument()
    expect(screen.getByText('Credit Score')).toBeInTheDocument()
    expect(screen.getByText('Status')).toBeInTheDocument()
    expect(screen.getByText('Date')).toBeInTheDocument()
  })

  it('renders application data', () => {
    render(<ApplicationTable {...defaultProps} />)

    expect(screen.getByText('Test User')).toBeInTheDocument()
    expect(screen.getByText('750')).toBeInTheDocument()
  })

  it('shows empty state when no applications', () => {
    render(
      <ApplicationTable
        {...defaultProps}
        applications={[]}
        totalCount={0}
      />,
    )

    expect(screen.getByText('No applications yet')).toBeInTheDocument()
  })

  it('shows loading skeletons', () => {
    render(<ApplicationTable {...defaultProps} isLoading={true} />)

    const skeletons = document.querySelectorAll('[class*="animate-pulse"]')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('shows pagination when multiple pages', () => {
    render(
      <ApplicationTable
        {...defaultProps}
        totalCount={50}
        page={1}
        pageSize={20}
      />,
    )

    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument()
    expect(screen.getByLabelText('Previous page')).toBeDisabled()
    expect(screen.getByLabelText('Next page')).not.toBeDisabled()
  })

  it('hides pagination for single page', () => {
    render(<ApplicationTable {...defaultProps} />)

    expect(screen.queryByText(/Page \d+ of/)).not.toBeInTheDocument()
  })
})
