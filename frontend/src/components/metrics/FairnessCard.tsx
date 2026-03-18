'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
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
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base">Fairness: {label}</CardTitle>
                  <CardDescription className="flex items-center gap-2 mt-1">
                    <span>Equalized Odds Diff: {eqOddsDiff.toFixed(4)}</span>
                  </CardDescription>
                </div>
                <Badge
                  className={passes80
                    ? 'bg-green-100 text-green-800 border-green-200'
                    : 'bg-red-100 text-red-800 border-red-200'
                  }
                  variant="outline"
                >
                  DI Ratio: {disparateImpact.toFixed(3)} {passes80 ? 'PASS' : 'FAIL'}
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="group" tick={{ fontSize: 12 }} />
                  <YAxis domain={[0, 100]} label={{ value: '%', angle: -90, position: 'insideLeft' }} />
                  <Tooltip formatter={(value: number) => `${value}%`} />
                  <Legend />
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
