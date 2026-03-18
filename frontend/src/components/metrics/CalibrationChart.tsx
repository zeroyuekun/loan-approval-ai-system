'use client'

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'

interface CalibrationChartProps {
  fractionOfPositives: number[]
  meanPredictedValue: number[]
  ece: number
}

export function CalibrationChart({ fractionOfPositives, meanPredictedValue, ece }: CalibrationChartProps) {
  if (!fractionOfPositives?.length || !meanPredictedValue?.length) return null

  const data = meanPredictedValue.map((predicted, i) => ({
    predicted: parseFloat(predicted.toFixed(3)),
    actual: parseFloat(fractionOfPositives[i].toFixed(3)),
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Calibration (Reliability Diagram)</CardTitle>
        <CardDescription>ECE: {ece.toFixed(4)} &mdash; {ece < 0.05 ? 'Well calibrated' : 'Needs improvement'}</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="predicted"
              label={{ value: 'Mean Predicted Probability', position: 'insideBottom', offset: -5 }}
              domain={[0, 1]}
            />
            <YAxis
              label={{ value: 'Fraction of Positives', angle: -90, position: 'insideLeft' }}
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
              dataKey="actual"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={{ r: 4 }}
              name="Actual"
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
