import { render, screen } from '@testing-library/react'
import { KpiStrip } from '@/components/metrics/KpiStrip'

describe('KpiStrip', () => {
  const metrics = { accuracy: 0.811, precision: 0.886, recall: 0.765, f1_score: 0.821, auc_roc: 0.871 }

  it('renders all five classic metric labels', () => {
    render(<KpiStrip metrics={metrics} />)
    for (const label of ['AUC-ROC', 'Accuracy', 'Precision', 'Recall', 'F1 Score']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows AUC as a 3-decimal hero value and rates as percentages', () => {
    render(<KpiStrip metrics={metrics} />)
    expect(screen.getByText('0.871')).toBeInTheDocument()   // AUC hero
    expect(screen.getByText('81.1%')).toBeInTheDocument()   // accuracy
  })

  it('renders an em dash for null values', () => {
    render(<KpiStrip metrics={{ accuracy: null, precision: null, recall: null, f1_score: null, auc_roc: null }} />)
    expect(screen.getAllByText('—').length).toBe(5)
  })
})
