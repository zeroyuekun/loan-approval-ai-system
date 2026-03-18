'use client'

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface ThresholdEntry {
  threshold: number
  precision: number
  recall: number
  f1: number
  fpr: number
  approval_rate: number
}

interface ThresholdChartProps {
  sweep: ThresholdEntry[]
  f1OptimalThreshold: number
  youdenJThreshold: number
  costOptimalThreshold: number
}

export function ThresholdChart({ sweep, f1OptimalThreshold, youdenJThreshold, costOptimalThreshold }: ThresholdChartProps) {
  if (!sweep?.length) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Threshold Analysis</CardTitle>
        <CardDescription className="flex flex-wrap gap-2 mt-1">
          <Badge variant="outline" className="bg-blue-50 text-blue-700">F1 Optimal: {f1OptimalThreshold}</Badge>
          <Badge variant="outline" className="bg-emerald-50 text-emerald-700">Youden&apos;s J: {youdenJThreshold}</Badge>
          <Badge variant="outline" className="bg-amber-50 text-amber-700">Cost Optimal: {costOptimalThreshold}</Badge>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={sweep}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="threshold"
              label={{ value: 'Threshold', position: 'insideBottom', offset: -5 }}
              domain={[0, 1]}
            />
            <YAxis domain={[0, 1]} />
            <Tooltip />
            <Legend />
            <ReferenceLine x={f1OptimalThreshold} stroke="#3b82f6" strokeDasharray="5 5" label="F1" />
            <ReferenceLine x={youdenJThreshold} stroke="#10b981" strokeDasharray="5 5" label="J" />
            <ReferenceLine x={costOptimalThreshold} stroke="#f59e0b" strokeDasharray="5 5" label="Cost" />
            <Line type="monotone" dataKey="precision" stroke="#8b5cf6" strokeWidth={1.5} dot={false} name="Precision" />
            <Line type="monotone" dataKey="recall" stroke="#ef4444" strokeWidth={1.5} dot={false} name="Recall" />
            <Line type="monotone" dataKey="f1" stroke="#3b82f6" strokeWidth={2} dot={false} name="F1" />
            <Line type="monotone" dataKey="approval_rate" stroke="#6b7280" strokeWidth={1.5} dot={false} name="Approval Rate" strokeDasharray="4 4" />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
