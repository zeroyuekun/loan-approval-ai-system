'use client'

import { useCallback, useState } from 'react'
import { cn } from '@/lib/utils'

export interface ChartHoverItem {
  key: string
  name: string
  value: number | string
  color: string
}

export interface ChartHoverState {
  label: string | number
  items: ChartHoverItem[]
}

/**
 * Minimal shape of the state object recharts passes to a categorical chart's
 * `onMouseMove` handler. We only read the few fields we need.
 */
interface RechartsTooltipState {
  isTooltipActive?: boolean
  activeLabel?: string | number
  activePayload?: Array<{
    dataKey?: string | number
    name?: string | number
    value?: number | string
    color?: string
    stroke?: string
    fill?: string
  }>
}

/**
 * Lifts recharts' active hover point into React state so it can be rendered in a
 * fixed panel BELOW the chart instead of a floating tooltip that covers the plot.
 *
 * Usage: spread `hoverProps` onto the recharts chart element and pair it with a
 * content-less `<Tooltip content={renderEmptyTooltip} />`. The empty Tooltip keeps
 * recharts' cursor crosshair and tells it to compute `activePayload`, while the
 * detail renders in a sibling <ChartHoverPanel /> under the chart.
 */
function sameHover(a: ChartHoverState | null, b: ChartHoverState): boolean {
  if (!a || a.label !== b.label || a.items.length !== b.items.length) return false
  return a.items.every((x, i) => {
    const y = b.items[i]
    return x.key === y.key && x.name === y.name && x.value === y.value && x.color === y.color
  })
}

export function useChartHover() {
  const [active, setActive] = useState<ChartHoverState | null>(null)

  const onMouseMove = useCallback((state: RechartsTooltipState) => {
    if (state?.isTooltipActive && state.activePayload && state.activePayload.length > 0) {
      const next: ChartHoverState = {
        label: state.activeLabel ?? '',
        items: state.activePayload
          .filter((p) => p.value !== undefined && p.value !== null)
          .map((p) => ({
            key: String(p.dataKey ?? p.name ?? ''),
            name: String(p.name ?? p.dataKey ?? ''),
            value: p.value as number | string,
            color: p.color || p.stroke || p.fill || 'hsl(var(--primary))',
          })),
      }
      // recharts fires onMouseMove on every pointer pixel; skip the state update
      // (and re-render) while the hovered point is unchanged.
      setActive((prev) => (sameHover(prev, next) ? prev : next))
    } else {
      setActive((prev) => (prev === null ? prev : null))
    }
  }, [])

  const onMouseLeave = useCallback(() => setActive(null), [])

  return { active, hoverProps: { onMouseMove, onMouseLeave } }
}

/**
 * Empty tooltip content. Keeps recharts' active-point tracking and cursor line
 * while rendering nothing that floats over the chart.
 */
export const renderEmptyTooltip = () => null

interface ChartHoverPanelProps {
  active: ChartHoverState | null
  /** Format a series value (mirrors recharts' tooltip `formatter` signature). */
  formatValue?: (value: number | string, name: string) => string
  /** Format the x-axis label (e.g. prefix "Threshold "). */
  formatLabel?: (label: string | number) => string
  /** Text shown when nothing is hovered. */
  placeholder?: string
  className?: string
}

/**
 * Fixed info strip rendered directly beneath a chart. Shows the hovered x-axis
 * label and every series value at that point, so the hover detail never covers
 * the graph. Reserves a stable min-height so the layout does not jump on hover.
 */
export function ChartHoverPanel({
  active,
  formatValue,
  formatLabel,
  placeholder = 'Hover over the chart to see values here',
  className,
}: ChartHoverPanelProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        'mt-3 flex min-h-[2.5rem] flex-wrap items-center gap-x-4 gap-y-1 rounded-md border bg-muted/40 px-3 py-2 text-xs',
        className,
      )}
    >
      {active && active.items.length > 0 ? (
        <>
          <span className="font-medium text-foreground">
            {formatLabel ? formatLabel(active.label) : active.label}
          </span>
          {active.items.map((item) => (
            <span key={item.key} className="flex items-center gap-1.5 text-muted-foreground">
              <span
                className="inline-block h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: item.color }}
                aria-hidden
              />
              {item.name}:{' '}
              <span className="font-medium tabular-nums text-foreground">
                {formatValue ? formatValue(item.value, item.name) : item.value}
              </span>
            </span>
          ))}
        </>
      ) : (
        <span className="text-muted-foreground">{placeholder}</span>
      )}
    </div>
  )
}
