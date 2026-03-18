'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface FeatureImportanceProps {
  features: Record<string, number> | Array<{ feature: string; importance: number }>
  title?: string
}

export function FeatureImportance({ features, title = 'Feature Importance' }: FeatureImportanceProps) {
  const data = (Array.isArray(features)
    ? features.map((f) => ({ name: f.feature.replace(/_/g, ' '), importance: f.importance }))
    : Object.entries(features).map(([name, importance]) => ({
        name: name.replace(/_/g, ' '),
        importance: Number(importance),
      }))
  ).sort((a, b) => b.importance - a.importance)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={Math.max(200, data.length * 35)}>
          <BarChart data={data} layout="vertical" margin={{ left: 80 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis dataKey="name" type="category" tick={{ fontSize: 12 }} width={100} />
            <Tooltip />
            <Bar dataKey="importance" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
