'use client'

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'

interface ROCCurveProps {
  fpr: number[]
  tpr: number[]
  auc: number
}

export function ROCCurve({ fpr, tpr, auc }: ROCCurveProps) {
  const data = fpr.map((x, i) => ({
    fpr: parseFloat(x.toFixed(3)),
    tpr: parseFloat(tpr[i].toFixed(3)),
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">ROC Curve</CardTitle>
        <CardDescription>AUC: {auc.toFixed(4)}</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="fpr"
              label={{ value: 'False Positive Rate', position: 'insideBottom', offset: -5 }}
              domain={[0, 1]}
            />
            <YAxis
              label={{ value: 'True Positive Rate', angle: -90, position: 'insideLeft' }}
              domain={[0, 1]}
            />
            <Tooltip />
            <ReferenceLine
              segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
              stroke="#999"
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
