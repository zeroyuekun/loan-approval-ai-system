'use client'

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AgentStep } from '@/types'
import { formatStepName } from './stepLabels'

interface StepLatencyChartProps {
  steps: AgentStep[]
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

function getStepDurationMs(step: AgentStep): number | null {
  if (!step.started_at || !step.completed_at) return null
  return new Date(step.completed_at).getTime() - new Date(step.started_at).getTime()
}

export function StepLatencyChart({ steps }: StepLatencyChartProps) {
  if (steps.length < 3) return null

  const data = steps
    .map((step) => {
      const durationMs = getStepDurationMs(step)
      if (durationMs === null) return null
      return {
        name: formatStepName(step.step_name),
        duration: durationMs,
        status: step.status,
      }
    })
    .filter(Boolean) as { name: string; duration: number; status: AgentStep['status'] }[]

  if (data.length < 2) return null

  const maxDuration = Math.max(...data.map((d) => d.duration))
  const useSeconds = maxDuration >= 1000

  const chartData = data.map((d) => ({
    ...d,
    displayDuration: useSeconds ? parseFloat((d.duration / 1000).toFixed(2)) : d.duration,
  }))

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Step Latency</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={Math.max(data.length * 40 + 20, 120)}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 20, bottom: 0, left: 0 }}>
            <XAxis
              type="number"
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              tickLine={{ stroke: '#4b5563' }}
              axisLine={{ stroke: '#4b5563' }}
              unit={useSeconds ? 's' : 'ms'}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={160}
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: 'hsl(var(--popover))',
                border: '1px solid hsl(var(--border))',
                borderRadius: '6px',
                color: 'hsl(var(--popover-foreground))',
                fontSize: 12,
              }}
              formatter={(value: number) => [
                useSeconds ? `${value}s` : `${value}ms`,
                'Duration',
              ]}
            />
            <Bar dataKey="displayDuration" radius={[0, 4, 4, 0]} maxBarSize={24}>
              {chartData.map((entry, index) => (
                <Cell key={index} fill={getStatusColor(entry.status)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
