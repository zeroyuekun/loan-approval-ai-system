import { render, screen } from '@testing-library/react'
import { RecentApplications } from '@/components/dashboard/RecentApplications'
import type { LoanApplication } from '@/types'

const mockApp = (id: string, firstName: string): LoanApplication => ({
  id,
  status: 'approved',
  loan_amount: 25000,
  created_at: '2026-05-25T00:00:00Z',
  updated_at: '2026-05-25T00:00:00Z',
  applicant: {
    id: 1,
    username: 'cust',
    email: 'cust@test.invalid',
    first_name: firstName,
    last_name: 'Test',
    role: 'customer',
  },
  decision: {
    decision: 'approved',
    confidence: 0.9,
    risk_score: 0.2,
    model_version: 'xgb-1',
    reasoning: 'ok',
    created_at: '2026-05-25T00:00:00Z',
  },
} as unknown as LoanApplication)

describe('RecentApplications', () => {
  it('renders applicant names', () => {
    render(<RecentApplications applications={[mockApp('a1', 'Alice'), mockApp('a2', 'Bob')]} />)
    expect(screen.getByText(/Alice/)).toBeInTheDocument()
    expect(screen.getByText(/Bob/)).toBeInTheDocument()
  })

  it('no longer renders an Open link to the application detail page', () => {
    render(<RecentApplications applications={[mockApp('a1', 'Alice')]} />)
    // The "Open →" link was removed; no row should link to the detail route.
    expect(screen.queryByRole('link', { name: /open application/i })).not.toBeInTheDocument()
    const links = screen.getAllByRole('link')
    expect(links.every((l) => !l.getAttribute('href')?.startsWith('/dashboard/applications/'))).toBe(true)
  })

  it('still links applicant name to customer profile (existing behaviour)', () => {
    render(<RecentApplications applications={[mockApp('a1', 'Alice')]} />)
    const nameLink = screen.getByRole('link', { name: /Alice Test/ })
    expect(nameLink).toHaveAttribute('href', '/dashboard/customers/1')
  })

  it('shows empty state when no applications', () => {
    render(<RecentApplications applications={[]} />)
    expect(screen.getByText(/No applications yet/i)).toBeInTheDocument()
  })
})
