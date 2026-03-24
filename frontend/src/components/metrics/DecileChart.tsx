'use client'

import { ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Label } from 'recharts'
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

  const safePercent = (v: number) => {
    const pct = v * 100;
    return Number.isFinite(pct) ? parseFloat(pct.toFixed(1)) : 0;
  };
  const safeFix = (v: number, digits: number) =>
    Number.isFinite(v) ? parseFloat(v.toFixed(digits)) : 0;

  const data = deciles.map(d => ({
    decile: `D${d.decile}`,
    'Approval Rate': safePercent(d.actual_rate),
    'Cumulative Rate': safePercent(d.cumulative_rate),
    Lift: safeFix(d.lift, 2),
    count: d.count,
  }))

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Decile Analysis (Gains Chart)</CardTitle>
        <CardDescription>Approval rate and lift by predicted probability decile (D1 = lowest)</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={380}>
          <ComposedChart data={data} margin={{ top: 10, right: 30, bottom: 10, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
            <XAxis dataKey="decile" tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }} />
            <YAxis yAxisId="left" domain={[0, 100]} tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }}>
              <Label value="%" angle={-90} position="insideLeft" offset={10} style={{ fontSize: 12, fill: '#6b7280', textAnchor: 'middle' }} />
            </YAxis>
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }}>
              <Label value="Lift" angle={90} position="insideRight" offset={10} style={{ fontSize: 12, fill: '#6b7280', textAnchor: 'middle' }} />
            </YAxis>
            <Tooltip />
            <Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
            <Bar yAxisId="left" dataKey="Approval Rate" fill="#60a5fa" radius={[4, 4, 0, 0]} />
            <Line yAxisId="right" type="monotone" dataKey="Lift" stroke="#ef4444" strokeWidth={2} dot={{ r: 3 }} />
            <Line yAxisId="left" type="monotone" dataKey="Cumulative Rate" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} strokeDasharray="4 4" />
          </ComposedChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
