import { render, screen } from '@testing-library/react'
import { StatusStrip } from '@/components/dashboard/StatusStrip'
import type { DashboardStatusStrip } from '@/types'

const greenStrip: DashboardStatusStrip = {
  drift: { level: 'none', detail: 'PSI 0.05' },
  fairness: { level: 'none', detail: 'Min DIR 0.92' },
  pending_review: { level: 'none', detail: 'No pending reviews', count: 0, oldest_age_hours: null, sla_breach: false },
  watchdog: { level: 'none', detail: 'Watchdog healthy', last_check: '2026-05-25T12:00:00+00:00' },
}

const amberStrip: DashboardStatusStrip = {
  drift: { level: 'moderate', detail: 'PSI 0.18' },
  fairness: { level: 'none', detail: 'Min DIR 0.95' },
  pending_review: { level: 'moderate', detail: '3 pending; oldest 8.5h', count: 3, oldest_age_hours: 8.5, sla_breach: false },
  watchdog: { level: 'moderate', detail: 'Degraded — 1 consecutive failures', last_check: '2026-05-25T12:00:00+00:00' },
}

const redStrip: DashboardStatusStrip = {
  drift: { level: 'significant', detail: 'PSI 0.32' },
  fairness: { level: 'significant', detail: 'Failing: gender' },
  pending_review: { level: 'significant', detail: '5 pending; oldest 30h (SLA breached)', count: 5, oldest_age_hours: 30, sla_breach: true },
  watchdog: { level: 'significant', detail: 'Backend unreachable — 3 failures', last_check: '2026-05-25T12:00:00+00:00' },
}

describe('StatusStrip', () => {
  it('renders all four indicators with labels', () => {
    render(<StatusStrip strip={greenStrip} />)
    expect(screen.getByText('Drift')).toBeInTheDocument()
    expect(screen.getByText('Fairness')).toBeInTheDocument()
    expect(screen.getByText('Pending Review')).toBeInTheDocument()
    expect(screen.getByText('Watchdog')).toBeInTheDocument()
  })

  it('shows detail strings inline', () => {
    render(<StatusStrip strip={greenStrip} />)
    expect(screen.getByText('PSI 0.05')).toBeInTheDocument()
    expect(screen.getByText('Min DIR 0.92')).toBeInTheDocument()
    expect(screen.getByText('No pending reviews')).toBeInTheDocument()
    expect(screen.getByText('Watchdog healthy')).toBeInTheDocument()
  })

  it('uses green dots when all levels are none', () => {
    const { container } = render(<StatusStrip strip={greenStrip} />)
    const greenDots = container.querySelectorAll('[data-testid="status-dot-none"]')
    expect(greenDots.length).toBe(4)
  })

  it('uses amber dots for moderate levels', () => {
    const { container } = render(<StatusStrip strip={amberStrip} />)
    expect(container.querySelectorAll('[data-testid="status-dot-moderate"]').length).toBe(3)
    expect(container.querySelectorAll('[data-testid="status-dot-none"]').length).toBe(1)
  })

  it('uses red dots and shows SLA breach badge for significant levels', () => {
    const { container } = render(<StatusStrip strip={redStrip} />)
    expect(container.querySelectorAll('[data-testid="status-dot-significant"]').length).toBe(4)
    // Two matches: the dedicated badge <span> + the detail text's parenthetical hint
    expect(screen.getAllByText(/SLA breached/i).length).toBeGreaterThanOrEqual(1)
  })

  it('renders an unknown indicator as a grey dot', () => {
    const partial = {
      ...greenStrip,
      drift: { level: 'unknown' as const, detail: 'No drift reports yet' },
    }
    const { container } = render(<StatusStrip strip={partial} />)
    expect(container.querySelector('[data-testid="status-dot-unknown"]')).toBeInTheDocument()
  })
})
