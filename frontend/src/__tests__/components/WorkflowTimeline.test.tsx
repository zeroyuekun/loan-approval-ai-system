import { render, screen } from '@testing-library/react'
import { WorkflowTimeline } from '@/components/agents/WorkflowTimeline'
import type { AgentStep } from '@/types'

vi.mock('@/components/agents/stepLabels', () => ({
  formatStepName: (name: string) => name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
  formatResultSummary: (summary: any) => {
    if (!summary) return []
    if (typeof summary === 'string') return [{ label: '', value: summary }]
    return Object.entries(summary).map(([k, v]) => ({ label: k, value: String(v) }))
  },
}))

function makeStep(overrides: Partial<AgentStep> = {}): AgentStep {
  return {
    step_name: 'credit_check',
    status: 'completed',
    started_at: '2026-03-30T10:00:00.000Z',
    completed_at: '2026-03-30T10:00:00.450Z',
    result_summary: null,
    ...overrides,
  } as AgentStep
}

describe('WorkflowTimeline', () => {
  it('renders step names formatted from snake_case', () => {
    render(<WorkflowTimeline steps={[makeStep({ step_name: 'bias_detection' })]} />)
    expect(screen.getByText('Bias Detection')).toBeInTheDocument()
  })

  it('shows duration for completed steps with timing', () => {
    render(
      <WorkflowTimeline
        steps={[
          makeStep({
            started_at: '2026-03-30T10:00:00.000Z',
            completed_at: '2026-03-30T10:00:00.450Z',
          }),
        ]}
      />
    )
    expect(screen.getByText('(450ms)')).toBeInTheDocument()
  })

  it('shows duration in seconds when >= 1000ms', () => {
    render(
      <WorkflowTimeline
        steps={[
          makeStep({
            started_at: '2026-03-30T10:00:00.000Z',
            completed_at: '2026-03-30T10:00:02.300Z',
          }),
        ]}
      />
    )
    expect(screen.getByText('(2.3s)')).toBeInTheDocument()
  })

  it('shows result summary items for object summaries', () => {
    render(
      <WorkflowTimeline
        steps={[
          makeStep({
            result_summary: { decision: 'approved', confidence: '0.92' },
          }),
        ]}
      />
    )
    expect(screen.getByText('approved')).toBeInTheDocument()
    expect(screen.getByText('0.92')).toBeInTheDocument()
    expect(screen.getByText('decision:')).toBeInTheDocument()
    expect(screen.getByText('confidence:')).toBeInTheDocument()
  })

  it('shows result summary for string summaries', () => {
    render(
      <WorkflowTimeline
        steps={[makeStep({ result_summary: 'Loan approved with conditions' })]}
      />
    )
    expect(screen.getByText('Loan approved with conditions')).toBeInTheDocument()
  })

  it('shows error text for failed steps', () => {
    render(
      <WorkflowTimeline
        steps={[
          makeStep({
            status: 'failed',
            error: 'Model inference timeout',
          }),
        ]}
      />
    )
    expect(screen.getByText('Model inference timeout')).toBeInTheDocument()
  })

  it('renders multiple steps in order', () => {
    const steps = [
      makeStep({ step_name: 'credit_check' }),
      makeStep({ step_name: 'bias_detection' }),
      makeStep({ step_name: 'email_generation' }),
    ]
    render(<WorkflowTimeline steps={steps} />)

    const names = screen.getAllByText(/Credit Check|Bias Detection|Email Generation/)
    expect(names).toHaveLength(3)
    expect(names[0]).toHaveTextContent('Credit Check')
    expect(names[1]).toHaveTextContent('Bias Detection')
    expect(names[2]).toHaveTextContent('Email Generation')
  })

  it('handles steps without timing data', () => {
    render(
      <WorkflowTimeline
        steps={[
          makeStep({
            step_name: 'pending_step',
            status: 'pending',
            started_at: undefined,
            completed_at: undefined,
          }),
        ]}
      />
    )
    expect(screen.getByText('Pending Step')).toBeInTheDocument()
    // No duration parenthetical should appear
    expect(screen.queryByText(/\(\d/)).not.toBeInTheDocument()
  })

  it('handles empty steps array', () => {
    const { container } = render(<WorkflowTimeline steps={[]} />)
    // The wrapper div should exist but be empty
    expect(container.firstChild).toBeInTheDocument()
    expect(container.firstChild).toBeEmptyDOMElement()
  })

  it('shows cumulative elapsed time for non-first steps', () => {
    const steps = [
      makeStep({
        step_name: 'step_one',
        started_at: '2026-03-30T10:00:00.000Z',
        completed_at: '2026-03-30T10:00:00.500Z',
      }),
      makeStep({
        step_name: 'step_two',
        started_at: '2026-03-30T10:00:00.500Z',
        completed_at: '2026-03-30T10:00:01.200Z',
      }),
      makeStep({
        step_name: 'step_three',
        started_at: '2026-03-30T10:00:01.200Z',
        completed_at: '2026-03-30T10:00:03.500Z',
      }),
    ]
    render(<WorkflowTimeline steps={steps} />)

    // Second step: completed_at 1200ms after pipeline start = +1.2s
    expect(screen.getByText('+1.2s')).toBeInTheDocument()
    // Third step: completed_at 3500ms after pipeline start = +3.5s
    expect(screen.getByText('+3.5s')).toBeInTheDocument()
  })

  it('does not show cumulative elapsed for the first step', () => {
    const steps = [
      makeStep({
        step_name: 'first_step',
        started_at: '2026-03-30T10:00:00.000Z',
        completed_at: '2026-03-30T10:00:00.500Z',
      }),
      makeStep({
        step_name: 'second_step',
        started_at: '2026-03-30T10:00:00.500Z',
        completed_at: '2026-03-30T10:00:01.000Z',
      }),
    ]
    render(<WorkflowTimeline steps={steps} />)

    // +500ms would be the first step's elapsed if it were shown — it should not appear
    // Only +1.0s for the second step should appear
    expect(screen.getByText('+1.0s')).toBeInTheDocument()
    expect(screen.queryByText('+500ms')).not.toBeInTheDocument()
  })
})
