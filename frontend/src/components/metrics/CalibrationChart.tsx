'use client'

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Label } from 'recharts'
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
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Calibration (Reliability Diagram)</CardTitle>
        <CardDescription>ECE: {ece.toFixed(4)} &mdash; {ece < 0.05 ? 'Well calibrated' : 'Needs improvement'}</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={350}>
          <LineChart data={data} margin={{ top: 10, right: 20, bottom: 30, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
            <XAxis
              dataKey="predicted"
              domain={[0, 1]}
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            >
              <Label value="Mean Predicted Probability" position="bottom" offset={10} style={{ fontSize: 12, fill: '#6b7280' }} />
            </XAxis>
            <YAxis
              domain={[0, 1]}
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            >
              <Label value="Fraction of Positives" angle={-90} position="left" offset={0} style={{ fontSize: 12, fill: '#6b7280', textAnchor: 'middle' }} />
            </YAxis>
            <Tooltip />
            <ReferenceLine
              segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
              stroke="#d1d5db"
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
