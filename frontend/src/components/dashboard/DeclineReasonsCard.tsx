'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { DashboardStats } from '@/types'

interface DeclineReasonsCardProps {
  data: DashboardStats['decline_reasons']
}

export function DeclineReasonsCard({ data }: DeclineReasonsCardProps) {
  const { reasons, total_declines: total, window_days: days } = data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top reasons for declines</CardTitle>
        <CardDescription>
          {total === 0
            ? `No applications declined in the last ${days} days.`
            : `Across ${total.toLocaleString('en-AU')} declined ${total === 1 ? 'application' : 'applications'} in the last ${days} days. One decline can have several reasons, so the percentages can add up to more than 100%.`}
        </CardDescription>
      </CardHeader>
      {reasons.length > 0 && (
        <CardContent>
          <ul className="space-y-4">
            {reasons.map((r) => (
              <li key={r.code}>
                <div className="flex items-baseline justify-between gap-4 text-sm">
                  <span>{r.reason}</span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">{r.share}%</span>
                </div>
                <div className="mt-1.5 h-2 rounded-full bg-muted" aria-hidden="true">
                  <div className="h-2 rounded-full bg-red-500/70" style={{ width: `${Math.min(100, r.share)}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
      )}
    </Card>
  )
}
