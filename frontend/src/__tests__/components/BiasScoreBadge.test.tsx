import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BiasScoreBadge } from '@/components/emails/BiasScoreBadge'

describe('BiasScoreBadge', () => {
  it('renders the score value', () => {
    render(<BiasScoreBadge score={42} categories={[]} />)
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('shows green styling for low bias (0-30)', () => {
    const { container } = render(<BiasScoreBadge score={15} categories={[]} />)
    const badge = container.querySelector('.bg-green-100')
    expect(badge).toBeInTheDocument()
  })

  it('shows yellow styling for moderate bias (31-60)', () => {
    const { container } = render(<BiasScoreBadge score={45} categories={[]} />)
    const badge = container.querySelector('.bg-yellow-100')
    expect(badge).toBeInTheDocument()
  })

  it('shows red styling for high bias (61+)', () => {
    const { container } = render(<BiasScoreBadge score={75} categories={[]} />)
    const badge = container.querySelector('.bg-red-100')
    expect(badge).toBeInTheDocument()
  })

  it('shows tooltip with categories on hover', async () => {
    const user = userEvent.setup()
    render(
      <BiasScoreBadge
        score={65}
        categories={['Gender bias', 'Age-based language']}
      />
    )

    // Tooltip not visible initially
    expect(screen.queryByText('Gender bias')).not.toBeInTheDocument()

    // Hover to show tooltip
    const badge = screen.getByText('65')
    await user.hover(badge.parentElement!)
    expect(screen.getByText('Gender bias')).toBeInTheDocument()
    expect(screen.getByText('Age-based language')).toBeInTheDocument()

    // Unhover to hide
    await user.unhover(badge.parentElement!)
    expect(screen.queryByText('Gender bias')).not.toBeInTheDocument()
  })

  it('does not show tooltip when categories are empty', async () => {
    const user = userEvent.setup()
    render(<BiasScoreBadge score={20} categories={[]} />)

    const badge = screen.getByText('20')
    await user.hover(badge.parentElement!)

    // No tooltip should appear even on hover when no categories
    expect(screen.queryByText('Bias Categories:')).not.toBeInTheDocument()
  })

  it('handles boundary scores correctly', () => {
    // Exact boundary: 30 should be green
    const { container: c1 } = render(<BiasScoreBadge score={30} categories={[]} />)
    expect(c1.querySelector('.bg-green-100')).toBeInTheDocument()

    // Exact boundary: 60 should be yellow
    const { container: c2 } = render(<BiasScoreBadge score={60} categories={[]} />)
    expect(c2.querySelector('.bg-yellow-100')).toBeInTheDocument()

    // Just above 60: should be red
    const { container: c3 } = render(<BiasScoreBadge score={61} categories={[]} />)
    expect(c3.querySelector('.bg-red-100')).toBeInTheDocument()
  })
})
