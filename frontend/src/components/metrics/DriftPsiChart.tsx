'use client'

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Label } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { DriftReport } from '@/types'

interface DriftPsiChartProps {
  reports: DriftReport[]
}

export function DriftPsiChart({ reports }: DriftPsiChartProps) {
  if (!reports.length) return null

  const data = [...reports]
    .reverse()
    .map((r) => ({
      date: r.report_date,
      psi: parseFloat((r.psi_score ?? 0).toFixed(4)),
    }))

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">PSI Over Time</CardTitle>
        <CardDescription>Population Stability Index trend across reporting periods</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={350}>
          <LineChart data={data} margin={{ top: 10, right: 20, bottom: 30, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            >
              <Label value="Report Date" position="bottom" offset={10} style={{ fontSize: 12, fill: '#6b7280' }} />
            </XAxis>
            <YAxis
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            >
              <Label value="PSI Score" angle={-90} position="left" offset={0} style={{ fontSize: 12, fill: '#6b7280', textAnchor: 'middle' }} />
            </YAxis>
            <Tooltip />
            <ReferenceLine
              y={0.10}
              stroke="#eab308"
              strokeDasharray="5 5"
              label={{ value: '0.10', position: 'right', fontSize: 10, fill: '#eab308' }}
            />
            <ReferenceLine
              y={0.25}
              stroke="#ef4444"
              strokeDasharray="5 5"
              label={{ value: '0.25', position: 'right', fontSize: 10, fill: '#ef4444' }}
            />
            <Line
              type="monotone"
              dataKey="psi"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={{ r: 3, fill: 'hsl(var(--primary))' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
