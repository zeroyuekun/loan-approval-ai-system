'use client'

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

interface ShapWaterfallProps {
  shapValues: Record<string, number>
}

export function ShapWaterfall({ shapValues }: ShapWaterfallProps) {
  const toTitleCase = (s: string) =>
    s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

  const data = Object.entries(shapValues)
    .map(([name, value]) => ({
      name: toTitleCase(name),
      value: Number(value),
    }))
    .filter((d) => Number.isFinite(d.value) && d.value !== 0)
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    .slice(0, 12)

  if (data.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">What Drove This Decision</CardTitle>
        <CardDescription>
          SHAP values show how each feature pushed the prediction toward approval (+) or denial (-)
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={Math.max(280, data.length * 36)}>
          <BarChart data={data} layout="vertical" margin={{ top: 5, right: 60, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }} />
            <YAxis
              dataKey="name"
              type="category"
              tick={{ fontSize: 11 }}
              width={160}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              formatter={(value: number) => [value.toFixed(4), 'SHAP Value']}
            />
            <Bar dataKey="value" radius={[0, 4, 4, 0]} label={{ position: 'right', fontSize: 10, formatter: (v: number) => v.toFixed(3) }}>
              {data.map((entry, index) => (
                <Cell key={index} fill={entry.value >= 0 ? '#22c55e' : '#ef4444'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
