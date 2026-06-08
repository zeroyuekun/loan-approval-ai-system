import { render, screen } from '@testing-library/react'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

function makeFeatures(n: number): Record<string, number> {
  const out: Record<string, number> = {}
  for (let i = 0; i < n; i++) out[`feature_${i}`] = (n - i) / n
  return out
}

describe('FeatureImportance', () => {
  it('caps to the top 15 features and notes how many are hidden', () => {
    render(<FeatureImportance features={makeFeatures(20)} />)
    // Highest-importance feature shown, 16th-ranked one not shown
    expect(screen.getByText('Feature 0')).toBeInTheDocument()
    expect(screen.queryByText('Feature 15')).not.toBeInTheDocument()
    expect(screen.getByText(/\+5 more/i)).toBeInTheDocument()
  })

  it('shows no "+N more" note when 15 or fewer features', () => {
    render(<FeatureImportance features={makeFeatures(10)} />)
    expect(screen.queryByText(/more/i)).not.toBeInTheDocument()
  })
})
