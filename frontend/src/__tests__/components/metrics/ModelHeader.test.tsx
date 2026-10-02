import { render, screen } from '@testing-library/react'
import { ModelHeader, TrainingBlockedNotice } from '@/components/metrics/ModelHeader'
import type { ModelMetrics } from '@/types'

const metrics = { algorithm: 'rf', version: '2.0.0', is_active: true } as unknown as ModelMetrics

function renderHeader(trainingStatus: 'success' | 'blocked', blockedGates: string[] = []) {
  return render(
    <ModelHeader
      metrics={metrics}
      isAdmin={false}
      selectedAlgorithm="rf"
      onSelect={() => {}}
      onTrain={() => {}}
      isTraining={false}
      activeTrainingLabel="Random Forest"
      trainingStatus={trainingStatus}
      blockedGates={blockedGates}
      trainErrorMessage={null}
    />,
  )
}

describe('ModelHeader training outcome', () => {
  it('warns, naming the blocking gates, when the new model was not activated', () => {
    renderHeader('blocked', ['promotion', 'validation'])
    expect(screen.getByRole('status')).toHaveTextContent(/not activated/i)
    expect(screen.getByRole('status')).toHaveTextContent(/promotion/i)
    expect(screen.getByRole('status')).toHaveTextContent(/validation sign-off/i)
    expect(screen.getByRole('status')).toHaveTextContent(/current model keeps serving/i)
    expect(screen.queryByText(/training complete/i)).not.toBeInTheDocument()
  })

  it('shows the plain success card only when the model was activated', () => {
    renderHeader('success')
    expect(screen.getByText(/training complete/i)).toBeInTheDocument()
    expect(screen.queryByText(/not activated/i)).not.toBeInTheDocument()
  })

  it('still warns when the gate list is missing', () => {
    render(<TrainingBlockedNotice gates={[]} />)
    expect(screen.getByRole('status')).toHaveTextContent(/not activated/i)
  })
})
