'use client'

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface ApprovalRateChartProps {
  approved: number
  denied: number
}

const COLORS = ['#10b981', '#ef4444']

export function ApprovalRateChart({ approved, denied }: ApprovalRateChartProps) {
  const total = approved + denied
  const data = [
    { name: 'Approved', value: approved, percent: total > 0 ? ((approved / total) * 100).toFixed(1) : '0' },
    { name: 'Denied', value: denied, percent: total > 0 ? ((denied / total) * 100).toFixed(1) : '0' },
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle>Approval Rate</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-8" role="img" aria-label={`Approval rate chart: ${data[0].percent}% approved, ${data[1].percent}% denied`}>
          <div className="flex-1">
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={data}
                  cx="50%"
                  cy="50%"
                  innerRadius={65}
                  outerRadius={95}
                  paddingAngle={3}
                  dataKey="value"
                  strokeWidth={0}
                >
                  {data.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    borderRadius: '10px',
                    border: '1px solid #e5e7eb',
                    boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)',
                    fontSize: '13px',
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="space-y-4">
            {data.map((item, i) => (
              <div key={item.name} className="flex items-center gap-3">
                <div className="h-3 w-3 rounded-full" style={{ backgroundColor: COLORS[i] }} aria-hidden="true" />
                <div>
                  <p className="text-sm font-medium">{item.name}</p>
                  <p className="text-2xl font-bold">{item.percent}%</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
