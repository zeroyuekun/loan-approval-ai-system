import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ConfusionMatrix } from '@/components/metrics/ConfusionMatrix'

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
})
