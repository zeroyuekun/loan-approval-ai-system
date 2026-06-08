import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  ChartHoverPanel,
  useChartHover,
  type ChartHoverState,
} from '@/components/metrics/ChartHoverPanel'

describe('ChartHoverPanel', () => {
  it('shows the placeholder when nothing is hovered', () => {
    render(<ChartHoverPanel active={null} placeholder="Hover me" />)
    expect(screen.getByText('Hover me')).toBeInTheDocument()
  })

  it('renders the hovered label and each series value', () => {
    const active: ChartHoverState = {
      label: 'D1',
      items: [
        { key: 'approval', name: 'Approval Rate', value: 42, color: '#60a5fa' },
        { key: 'lift', name: 'Lift', value: 1.3, color: '#ef4444' },
      ],
    }
    render(<ChartHoverPanel active={active} />)
    expect(screen.getByText('D1')).toBeInTheDocument()
    expect(screen.getByText(/Approval Rate/)).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('1.3')).toBeInTheDocument()
  })

  it('applies the value and label formatters', () => {
    const active: ChartHoverState = {
      label: 0.3,
      items: [{ key: 'tpr', name: 'TPR', value: 85, color: '#000' }],
    }
    render(
      <ChartHoverPanel
        active={active}
        formatLabel={(l) => `FPR ${l}`}
        formatValue={(v) => `${v}%`}
      />,
    )
    expect(screen.getByText('FPR 0.3')).toBeInTheDocument()
    expect(screen.getByText('85%')).toBeInTheDocument()
  })

  it('falls back to the placeholder when the active point has no items', () => {
    render(<ChartHoverPanel active={{ label: 'x', items: [] }} placeholder="Nothing" />)
    expect(screen.getByText('Nothing')).toBeInTheDocument()
  })
})

/** Harness that drives the hook the way recharts' chart events would. */
function HookHarness() {
  const { active, hoverProps } = useChartHover()
  return (
    <div>
      <button
        onClick={() =>
          hoverProps.onMouseMove({
            isTooltipActive: true,
            activeLabel: 'D1',
            activePayload: [{ dataKey: 'a', name: 'Series A', value: 5, color: '#f00' }],
          })
        }
      >
        move
      </button>
      <button onClick={() => hoverProps.onMouseMove({ isTooltipActive: false })}>move-inactive</button>
      <button onClick={() => hoverProps.onMouseLeave()}>leave</button>
      <ChartHoverPanel active={active} placeholder="idle" />
    </div>
  )
}

describe('useChartHover', () => {
  it('captures the active payload on move and clears it on leave', async () => {
    const user = userEvent.setup()
    render(<HookHarness />)

    expect(screen.getByText('idle')).toBeInTheDocument()

    await user.click(screen.getByText('move'))
    expect(screen.getByText('D1')).toBeInTheDocument()
    expect(screen.getByText(/Series A/)).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()

    await user.click(screen.getByText('leave'))
    expect(screen.getByText('idle')).toBeInTheDocument()
  })

  it('clears the active payload when the chart reports no active point', async () => {
    const user = userEvent.setup()
    render(<HookHarness />)
    await user.click(screen.getByText('move'))
    expect(screen.getByText('D1')).toBeInTheDocument()
    await user.click(screen.getByText('move-inactive'))
    expect(screen.getByText('idle')).toBeInTheDocument()
  })
})
