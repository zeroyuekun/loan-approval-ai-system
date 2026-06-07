import { render, screen } from '@testing-library/react'
import { DriftPanel } from '@/components/metrics/DriftPanel'
import { DriftReport } from '@/types'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

const reports: DriftReport[] = [
  {
    id: 'r2', report_date: '2026-06-01', psi_score: 0.07, psi_per_feature: {},
    mean_probability: 0.42, std_probability: 0.2, approval_rate: 0.55,
    drift_detected: false, alert_level: 'none', num_predictions: 1200,
    period_start: '2026-05-01', period_end: '2026-06-01',
  },
  {
    id: 'r1', report_date: '2026-05-01', psi_score: 0.03, psi_per_feature: {},
    mean_probability: 0.4, std_probability: 0.2, approval_rate: 0.5,
    drift_detected: false, alert_level: 'none', num_predictions: 1000,
    period_start: '2026-04-01', period_end: '2026-05-01',
  },
]

describe('DriftPanel', () => {
  it('shows the latest PSI, status, and prediction count', () => {
    render(<DriftPanel reports={reports} />)
    expect(screen.getByText('0.0700')).toBeInTheDocument()      // latest psi (reports[0])
    expect(screen.getByText('Stable')).toBeInTheDocument()       // alert_level none
    expect(screen.getByText('1,200')).toBeInTheDocument()        // num_predictions
  })

  it('renders nothing when there are no reports', () => {
    const { container } = render(<DriftPanel reports={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})
