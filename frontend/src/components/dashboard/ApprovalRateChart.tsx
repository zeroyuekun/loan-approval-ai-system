'use client'

import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface ApprovalRateChartProps {
  approved: number
  denied: number
}

const COLORS = ['#22c55e', '#ef4444']

export function ApprovalRateChart({ approved, denied }: ApprovalRateChartProps) {
  const total = approved + denied
  const data = [
    { name: 'Approved', value: approved, percent: total > 0 ? ((approved / total) * 100).toFixed(1) : '0' },
    { name: 'Denied', value: denied, percent: total > 0 ? ((denied / total) * 100).toFixed(1) : '0' },
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Approval Rate</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={100}
              paddingAngle={5}
              dataKey="value"
              label={({ name, percent }) => `${name}: ${percent}%`}
            >
              {data.map((_, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index]} />
              ))}
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
