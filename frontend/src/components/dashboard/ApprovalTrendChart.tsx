'use client'

import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'

interface ApprovalTrendChartProps {
  data: { date: string; rate: number }[]
}

export function ApprovalTrendChart({ data }: ApprovalTrendChartProps) {
  if (!data.length) return null

  const formatted = data.map((d) => ({
    ...d,
    date: new Date(d.date).toLocaleDateString('en-AU', { month: 'short', day: 'numeric' }),
  }))

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Approval Rate Trend</CardTitle>
        <CardDescription>Daily approval rate over the last 30 days</CardDescription>
      </CardHeader>
      <CardContent>
        {/* TODO: add proper aria labels */}
        <div>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={formatted} margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
            <defs>
              <linearGradient id="approvalGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                borderRadius: '10px',
                border: '1px solid #e5e7eb',
                boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)',
                fontSize: '13px',
              }}
              formatter={(value: number) => [`${value}%`, 'Approval Rate']}
            />
            <Area
              type="monotone"
              dataKey="rate"
              stroke="#10b981"
              strokeWidth={2}
              fill="url(#approvalGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
