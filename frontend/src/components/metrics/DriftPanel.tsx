'use client'

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Label } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { DriftReport } from '@/types'
import { useChartHover, ChartHoverPanel, renderEmptyTooltip } from './ChartHoverPanel'

interface DriftPanelProps {
  reports: DriftReport[]
}

const ALERT_CONFIG: Record<string, { label: string; variant: 'success' | 'warning' | 'destructive' }> = {
  none: { label: 'Stable', variant: 'success' },
  moderate: { label: 'Investigate', variant: 'warning' },
  significant: { label: 'Action Required', variant: 'destructive' },
}

export function DriftPanel({ reports }: DriftPanelProps) {
  const { active, hoverProps } = useChartHover()
  if (!reports.length) return null

  const latest = reports[0]
  const config = ALERT_CONFIG[latest.alert_level] || ALERT_CONFIG.none
  const trend = [...reports].reverse().map((r) => ({
    date: r.report_date,
    psi: parseFloat((r.psi_score ?? 0).toFixed(4)),
  }))

  const stats = [
    { label: 'Report Date', value: latest.report_date },
    { label: 'Predictions', value: latest.num_predictions.toLocaleString() },
    { label: 'Approval Rate', value: latest.approval_rate != null ? `${(latest.approval_rate * 100).toFixed(1)}%` : '—' },
    { label: 'Mean Probability', value: latest.mean_probability != null ? latest.mean_probability.toFixed(4) : '—' },
  ]

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Data Drift (PSI)</CardTitle>
          <Badge variant={config.variant}>{config.label}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-4">
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Latest PSI Score</p>
              <p className="text-3xl font-bold tabular-nums">
                {latest.psi_score != null ? latest.psi_score.toFixed(4) : '—'}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              {stats.map((s) => (
                <div key={s.label}>
                  <p className="mb-0.5 text-xs font-medium text-muted-foreground">{s.label}</p>
                  <p className="text-sm font-medium tabular-nums">{s.value}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trend} margin={{ top: 10, right: 20, bottom: 30, left: 10 }} {...hoverProps}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }}>
                  <Label value="Report Date" position="bottom" offset={10} style={{ fontSize: 12, fill: '#6b7280' }} />
                </XAxis>
                <YAxis tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }} />
                <Tooltip content={renderEmptyTooltip} />
                <ReferenceLine y={0.10} stroke="#eab308" strokeDasharray="5 5" label={{ value: '0.10', position: 'right', fontSize: 10, fill: '#eab308' }} />
                <ReferenceLine y={0.25} stroke="#ef4444" strokeDasharray="5 5" label={{ value: '0.25', position: 'right', fontSize: 10, fill: '#ef4444' }} />
                <Line type="monotone" dataKey="psi" name="PSI" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 3, fill: 'hsl(var(--primary))' }} />
              </LineChart>
            </ResponsiveContainer>
            <ChartHoverPanel active={active} />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
