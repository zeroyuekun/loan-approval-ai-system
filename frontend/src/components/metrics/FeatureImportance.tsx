'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface FeatureImportanceProps {
  features: Record<string, number> | Array<{ feature: string; importance: number }>
  title?: string
}

export function FeatureImportance({ features, title = 'Feature Importance' }: FeatureImportanceProps) {
  const toTitleCase = (s: string) =>
    s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

  const data = (Array.isArray(features)
    ? features
        .filter((f): f is { feature: string; importance: number } =>
          f != null && typeof f === 'object' && 'feature' in f && 'importance' in f
        )
        .map((f) => ({ name: toTitleCase(f.feature), importance: f.importance }))
    : Object.entries(features).map(([name, importance]) => ({
        name: toTitleCase(name),
        importance: Number(importance),
      }))
  )
    .filter((d) => Number.isFinite(d.importance) && d.importance > 0)
    .sort((a, b) => b.importance - a.importance)

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={Math.max(280, data.length * 36)}>
          <BarChart data={data} layout="vertical" margin={{ top: 5, right: 30, bottom: 5, left: 10 }}>
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
            <Tooltip />
            <Bar dataKey="importance" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
