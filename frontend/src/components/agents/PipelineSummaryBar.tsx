'use client'

import { useState } from 'react'
import { AgentStep } from '@/types'
import { formatStepName } from './stepLabels'

interface PipelineSummaryBarProps {
  steps: AgentStep[]
}

function getStepDurationMs(step: AgentStep): number | null {
  if (!step.started_at || !step.completed_at) return null
  return new Date(step.completed_at).getTime() - new Date(step.started_at).getTime()
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function getStatusColor(status: AgentStep['status']): string {
  switch (status) {
    case 'completed':
      return '#22c55e'
    case 'failed':
      return '#ef4444'
    case 'running':
      return '#3b82f6'
    default:
      return '#6b7280'
  }
}

export function PipelineSummaryBar({ steps }: PipelineSummaryBarProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)

  if (steps.length === 0) return null

  const durations = steps.map((step) => getStepDurationMs(step))
  const hasTimings = durations.some((d) => d !== null)
  const totalMs = durations.reduce((sum, d) => sum + (d ?? 0), 0)

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2">
        <div className="flex-1 flex h-3 rounded-full overflow-hidden bg-muted/30">
          {steps.map((step, i) => {
            const durationMs = durations[i]
            const widthPct = hasTimings && totalMs > 0 && durationMs !== null
              ? Math.max((durationMs / totalMs) * 100, 2)
              : 100 / steps.length

            return (
              <div
                key={i}
                className="relative h-full transition-opacity duration-150"
                style={{
                  width: `${widthPct}%`,
                  backgroundColor: getStatusColor(step.status),
                  opacity: hoveredIndex !== null && hoveredIndex !== i ? 0.4 : 1,
                }}
                onMouseEnter={() => setHoveredIndex(i)}
                onMouseLeave={() => setHoveredIndex(null)}
              >
                {hoveredIndex === i && (
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-10 whitespace-nowrap rounded-md bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-md border border-border">
                    <p className="font-medium">{formatStepName(step.step_name)}</p>
                    <p className="text-muted-foreground">
                      {durationMs !== null ? formatDuration(durationMs) : 'No timing data'}
                    </p>
                  </div>
                )}
              </div>
            )
          })}
        </div>
        {hasTimings && totalMs > 0 && (
          <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
            {formatDuration(totalMs)}
          </span>
        )}
      </div>
    </div>
  )
}
