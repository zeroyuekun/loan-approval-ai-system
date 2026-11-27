'use client'

import { Bar, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

interface ApprovalTrendChartProps {
  volume: Array<{ date: string; count: number }>
  approvalTrend: Array<{ date: string; rate: number }>
}

function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

export function ApprovalTrendChart({ volume, approvalTrend }: ApprovalTrendChartProps) {
  const rateByDate = new Map(approvalTrend.map((d) => [d.date, d.rate]))
  const data = volume.map((d) => ({
    date: shortDate(d.date),
    applications: d.count,
    approvalRate: rateByDate.get(d.date) ?? null,
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Applications &amp; approval rate</CardTitle>
        <CardDescription>
          Last 30 days. Bars show how many applications arrived each day; the line shows the share approved. A sudden
          drop in the line can mean stricter rules or a data problem.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">No applications in the last 30 days.</p>
        ) : (
          <div role="img" aria-label={`Applications and approval rate over the last 30 days, ${data.length} days with activity`}>
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <XAxis dataKey="date" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <YAxis yAxisId="count" allowDecimals={false} tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                <YAxis
                  yAxisId="rate"
                  orientation="right"
                  domain={[0, 100]}
                  tickFormatter={(v) => `${v}%`}
                  tick={{ fontSize: 12 }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  formatter={(value, name) =>
                    name === 'approvalRate' ? [`${value}%`, 'Approved'] : [value, 'Applications']
                  }
                  contentStyle={{ borderRadius: '10px', fontSize: '13px' }}
                />
                <Bar yAxisId="count" dataKey="applications" fill="hsl(var(--chart-1) / 0.25)" radius={[4, 4, 0, 0]} />
                <Line
                  yAxisId="rate"
                  dataKey="approvalRate"
                  stroke="hsl(var(--chart-1))"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
