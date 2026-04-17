import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/lib/auth'
import { Sidebar } from '@/components/layout/Sidebar'

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/dashboard'),
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>{children}</a>
  ),
}))

vi.mock('@/lib/auth', () => ({
  useAuth: vi.fn(() => ({
    user: { username: 'admin', first_name: 'Admin', last_name: 'User', role: 'admin' },
  })),
}))

vi.mock('@/components/ui/logo', () => ({
  LogoIcon: () => <div data-testid="logo-icon" />,
}))

const defaultProps = {
  isOpen: false,
  onClose: vi.fn(),
}

describe('Sidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(usePathname).mockReturnValue('/dashboard')
    vi.mocked(useAuth).mockReturnValue({
      user: { username: 'admin', first_name: 'Admin', last_name: 'User', role: 'admin' },
    } as ReturnType<typeof useAuth>)
  })

  it('renders brand name "AussieLoanAI"', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('AussieLoanAI')).toBeInTheDocument()
  })

  it('shows all nav items for admin user', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Applications')).toBeInTheDocument()
    expect(screen.getByText('Human Review')).toBeInTheDocument()
    expect(screen.getByText('Customers')).toBeInTheDocument()
    expect(screen.getByText('My Profile')).toBeInTheDocument()
    expect(screen.getByText('Model Metrics')).toBeInTheDocument()
    expect(screen.getByText('Emails')).toBeInTheDocument()
    expect(screen.getByText('Audit Log')).toBeInTheDocument()
  })

  it('hides staffOnly items for customer user', () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { username: 'jane', first_name: 'Jane', last_name: 'Doe', role: 'customer' },
    } as ReturnType<typeof useAuth>)

    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Applications')).toBeInTheDocument()
    expect(screen.getByText('My Profile')).toBeInTheDocument()
    expect(screen.getByText('Model Metrics')).toBeInTheDocument()
    expect(screen.getByText('Emails')).toBeInTheDocument()

    expect(screen.queryByText('Human Review')).not.toBeInTheDocument()
    expect(screen.queryByText('Customers')).not.toBeInTheDocument()
    expect(screen.queryByText('Audit Log')).not.toBeInTheDocument()
  })

  it('shows user display name in user card', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('Admin User')).toBeInTheDocument()
  })

  it('shows user role in user card', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('admin')).toBeInTheDocument()
  })

  it('shows first initial in avatar', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('A')).toBeInTheDocument()
  })

  it('calls onClose when overlay is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()

    render(<Sidebar isOpen={true} onClose={onClose} />)

    const overlay = screen.getByRole('button', { name: 'Close sidebar' })
    await user.click(overlay)

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('sidebar is hidden when isOpen=false (has -translate-x-full class)', () => {
    render(<Sidebar isOpen={false} onClose={vi.fn()} />)
    const aside = screen.getByLabelText('Main navigation')
    expect(aside).toHaveClass('-translate-x-full')
  })

  it('sidebar is visible when isOpen=true (has translate-x-0 class)', () => {
    render(<Sidebar isOpen={true} onClose={vi.fn()} />)
    const aside = screen.getByLabelText('Main navigation')
    expect(aside).toHaveClass('translate-x-0')
  })
})
