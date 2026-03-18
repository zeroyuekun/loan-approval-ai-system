'use client'

import { ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'

interface DecileEntry {
  decile: number
  count: number
  actual_rate: number
  cumulative_rate: number
  lift: number
}

interface DecileChartProps {
  deciles: DecileEntry[]
}

export function DecileChart({ deciles }: DecileChartProps) {
  if (!deciles?.length) return null

  const data = deciles.map(d => ({
    decile: `D${d.decile}`,
    'Approval Rate': parseFloat((d.actual_rate * 100).toFixed(1)),
    'Cumulative Rate': parseFloat((d.cumulative_rate * 100).toFixed(1)),
    Lift: parseFloat(d.lift.toFixed(2)),
    count: d.count,
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Decile Analysis (Gains Chart)</CardTitle>
        <CardDescription>Approval rate and lift by predicted probability decile (D1 = lowest probability)</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="decile" />
            <YAxis yAxisId="left" domain={[0, 100]} label={{ value: '%', angle: -90, position: 'insideLeft' }} />
            <YAxis yAxisId="right" orientation="right" label={{ value: 'Lift', angle: 90, position: 'insideRight' }} />
            <Tooltip />
            <Legend />
            <Bar yAxisId="left" dataKey="Approval Rate" fill="#60a5fa" radius={[4, 4, 0, 0]} />
            <Line yAxisId="right" type="monotone" dataKey="Lift" stroke="#ef4444" strokeWidth={2} dot={{ r: 3 }} />
            <Line yAxisId="left" type="monotone" dataKey="Cumulative Rate" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} strokeDasharray="4 4" />
          </ComposedChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
