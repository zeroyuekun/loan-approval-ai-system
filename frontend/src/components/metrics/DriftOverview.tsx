'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { DriftReport } from '@/types'

interface DriftOverviewProps {
  reports: DriftReport[]
}

export function DriftOverview({ reports }: DriftOverviewProps) {
  if (!reports.length) return null

  const latest = reports[0]

  const alertConfig: Record<string, { label: string; variant: 'success' | 'warning' | 'destructive' }> = {
    none: { label: 'Stable', variant: 'success' },
    moderate: { label: 'Investigate', variant: 'warning' },
    significant: { label: 'Action Required', variant: 'destructive' },
  }

  const config = alertConfig[latest.alert_level] || alertConfig.none

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Drift Status</CardTitle>
          <Badge variant={config.variant}>{config.label}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">Overall PSI Score</p>
            <p className="text-3xl font-bold tabular-nums">
              {latest.psi_score != null ? latest.psi_score.toFixed(4) : '—'}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4 pt-2">
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-0.5">Report Date</p>
              <p className="text-sm font-medium tabular-nums">{latest.report_date}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-0.5">Predictions</p>
              <p className="text-sm font-medium tabular-nums">{latest.num_predictions.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-0.5">Approval Rate</p>
              <p className="text-sm font-medium tabular-nums">
                {latest.approval_rate != null ? `${(latest.approval_rate * 100).toFixed(1)}%` : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-0.5">Mean Probability</p>
              <p className="text-sm font-medium tabular-nums">
                {latest.mean_probability != null ? latest.mean_probability.toFixed(4) : '—'}
              </p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
