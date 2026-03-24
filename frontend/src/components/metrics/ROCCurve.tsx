'use client'

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Label } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'

interface ROCCurveProps {
  fpr: number[]
  tpr: number[]
  auc: number
}

export function ROCCurve({ fpr, tpr, auc }: ROCCurveProps) {
  if (!fpr?.length || !tpr?.length) return null

  const data = fpr.map((x, i) => ({
    fpr: parseFloat(x.toFixed(3)),
    tpr: parseFloat(tpr[i].toFixed(3)),
  }))

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">ROC Curve</CardTitle>
        <CardDescription>AUC: {auc != null ? auc.toFixed(4) : '—'}</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={350}>
          <LineChart data={data} margin={{ top: 10, right: 20, bottom: 30, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
            <XAxis
              dataKey="fpr"
              domain={[0, 1]}
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            >
              <Label value="False Positive Rate" position="bottom" offset={10} style={{ fontSize: 12, fill: '#6b7280' }} />
            </XAxis>
            <YAxis
              domain={[0, 1]}
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            >
              <Label value="True Positive Rate" angle={-90} position="left" offset={0} style={{ fontSize: 12, fill: '#6b7280', textAnchor: 'middle' }} />
            </YAxis>
            <Tooltip />
            <ReferenceLine
              segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
              stroke="#d1d5db"
              strokeDasharray="5 5"
            />
            <Line
              type="monotone"
              dataKey="tpr"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
