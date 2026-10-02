import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ConfusionMatrix } from '@/components/metrics/ConfusionMatrix'
import { PerformanceTab } from '@/components/metrics/tabs/PerformanceTab'
import type { ModelMetrics } from '@/types'

describe('ConfusionMatrix', () => {
  const matrix = { tp: 80, fp: 20, tn: 850, fn: 50 }

  it('renders the four cell counts and the sample total', () => {
    render(<ConfusionMatrix matrix={matrix} />)
    expect(screen.getByText('80')).toBeInTheDocument()
    expect(screen.getByText(/Total: 1000 samples/)).toBeInTheDocument()
  })

  it('labels the operating threshold the counts were computed at', () => {
    // Honesty: a confusion matrix with no threshold reads as a 0.5 classifier.
    render(<ConfusionMatrix matrix={matrix} threshold={0.55} />)
    expect(screen.getByText(/at operating threshold 0\.55/)).toBeInTheDocument()
  })

  it('omits the threshold label when none is provided', () => {
    render(<ConfusionMatrix matrix={matrix} />)
    expect(screen.queryByText(/operating threshold/)).not.toBeInTheDocument()
  })

  it('flags counts computed at a threshold the model no longer serves at', () => {
    render(<ConfusionMatrix matrix={matrix} threshold={0.5} servingThreshold={0.87} />)
    expect(screen.getByText(/at operating threshold 0\.50/)).toBeInTheDocument()
    expect(screen.getByText(/now serves at 0\.87/)).toBeInTheDocument()
  })

  it('shows no notice when the counts match the serving threshold', () => {
    render(<ConfusionMatrix matrix={matrix} threshold={0.87} servingThreshold={0.87} />)
    expect(screen.queryByText(/now serves at/)).not.toBeInTheDocument()
  })

  it('performance tab labels the matrix with the threshold its metrics were computed at', () => {
    const metrics = {
      confusion_matrix: matrix,
      optimal_threshold: 0.87,
      training_metadata: { metrics_threshold: 0.5 },
    } as unknown as ModelMetrics
    render(<PerformanceTab metrics={metrics} />)
    expect(screen.getByText(/at operating threshold 0\.50/)).toBeInTheDocument()
    expect(screen.getByText(/now serves at 0\.87/)).toBeInTheDocument()
  })
})
