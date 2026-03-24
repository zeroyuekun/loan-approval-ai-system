'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Label } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface FairnessCardProps {
  fairnessMetrics: Record<string, any>
}

export function FairnessCard({ fairnessMetrics }: FairnessCardProps) {
  if (!fairnessMetrics || Object.keys(fairnessMetrics).length === 0) return null

  return (
    <div className="space-y-6">
      {Object.entries(fairnessMetrics).map(([attribute, data]) => {
        if (!data?.groups) return null
        const groups = data.groups as Record<string, { count: number; actual_approval_rate: number; predicted_approval_rate: number; tpr: number; fpr: number }>
        const disparateImpact: number = data.disparate_impact_ratio ?? 1
        const eqOddsDiff: number = data.equalized_odds_difference ?? 0
        const passes80: boolean = data.passes_80_percent_rule ?? true

        const chartData = Object.entries(groups).map(([group, vals]) => ({
          group: group.replace(/_/g, ' '),
          'Actual Approval': parseFloat((vals.actual_approval_rate * 100).toFixed(1)),
          'Predicted Approval': parseFloat((vals.predicted_approval_rate * 100).toFixed(1)),
          TPR: parseFloat((vals.tpr * 100).toFixed(1)),
          FPR: parseFloat((vals.fpr * 100).toFixed(1)),
          count: vals.count,
        }))

        const label = attribute.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

        return (
          <Card key={attribute}>
            <CardHeader className="pb-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <CardTitle className="text-base">Fairness: {label}</CardTitle>
                  <CardDescription className="mt-1.5">
                    Equalized Odds Diff: {eqOddsDiff.toFixed(4)}
                  </CardDescription>
                </div>
                <Badge
                  className={`shrink-0 ${passes80
                    ? 'bg-green-100 text-green-800 border-green-200'
                    : 'bg-red-100 text-red-800 border-red-200'
                  }`}
                  variant="outline"
                >
                  DI: {disparateImpact.toFixed(3)} {passes80 ? 'PASS' : 'FAIL'}
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={chartData} margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
                  <XAxis
                    dataKey="group"
                    tick={{ fontSize: 10 }}
                    interval={0}
                    angle={-25}
                    textAnchor="end"
                    height={60}
                    tickLine={{ stroke: '#d1d5db' }}
                  />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }}>
                    <Label value="%" angle={-90} position="insideLeft" offset={10} style={{ fontSize: 12, fill: '#6b7280', textAnchor: 'middle' }} />
                  </YAxis>
                  <Tooltip formatter={(value: number) => `${value}%`} />
                  <Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
                  <Bar dataKey="Actual Approval" fill="#60a5fa" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="Predicted Approval" fill="#34d399" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="TPR" fill="#a78bfa" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="FPR" fill="#fb923c" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
