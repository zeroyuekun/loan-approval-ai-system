import { render, screen } from '@testing-library/react'
import { DiagnosticsTab } from '@/components/metrics/tabs/DiagnosticsTab'
import { ModelMetrics } from '@/types'

const CAPTION_TEXT = /same split used for early\s*stopping, probability calibration and threshold choice/

function makeMetrics(trainingMetadata: Record<string, unknown> | null | undefined): ModelMetrics {
  return {
    training_metadata: trainingMetadata,
  } as unknown as ModelMetrics
}

describe('DiagnosticsTab — validation-split caveat', () => {
  it('shows the caption when val_auc is present in training metadata', () => {
    render(<DiagnosticsTab metrics={makeMetrics({ train_size: 8000, val_auc: 0.83, overfitting_gap_val: 0.07 })} />)
    expect(screen.getByText(CAPTION_TEXT)).toBeInTheDocument()
  })

  it('does not show the caption when val_auc is absent', () => {
    render(<DiagnosticsTab metrics={makeMetrics({ train_size: 8000, overfitting_gap: 0.07 })} />)
    expect(screen.queryByText(CAPTION_TEXT)).not.toBeInTheDocument()
  })

  it('does not show the caption when there is no training metadata at all', () => {
    render(<DiagnosticsTab metrics={makeMetrics(null)} />)
    expect(screen.queryByText(CAPTION_TEXT)).not.toBeInTheDocument()
  })
})
