'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatPercent } from '@/lib/utils'
import type { DashboardStats } from '@/types'

interface DecisionHandlingCardProps {
  data: DashboardStats['decision_handling']
}

export function DecisionHandlingCard({ data }: DecisionHandlingCardProps) {
  const { total } = data
  const rows = [
    { label: 'Decided automatically', count: data.automated, color: 'bg-blue-500' },
    { label: 'Checked by staff, decision kept', count: data.reviewed, color: 'bg-amber-500' },
    { label: 'Changed by staff', count: data.overridden, color: 'bg-red-500' },
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Who made the decision</CardTitle>
        <CardDescription>
          How often a person was involved in the final decision. A high &ldquo;changed by staff&rdquo; share means the
          model and the lending team disagree and the model should be checked.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="text-sm text-muted-foreground">No decisions yet.</p>
        ) : (
          <>
            <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden="true">
              {rows.map((r) => (
                <div key={r.label} className={r.color} style={{ width: formatPercent(r.count / total) }} />
              ))}
            </div>
            <ul className="mt-4 space-y-2 text-sm">
              {rows.map((r) => (
                <li key={r.label} className="flex items-center justify-between gap-4">
                  <span className="flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${r.color}`} aria-hidden="true" />
                    {r.label}
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    {r.count.toLocaleString('en-AU')} ({formatPercent(r.count / total)})
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  )
}
