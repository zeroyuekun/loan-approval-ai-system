'use client'

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
  Label,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { DriftReport } from '@/types'
import { PSI_STABLE, PSI_DRIFT } from '@/lib/benchmarks'

interface DriftTrendChartProps {
  reports: DriftReport[]
}

/**
 * DriftTrendChart — population stability + operational reality on one chart.
 * Renamed from DriftPsiChart and gained an approval-rate series so a lending
 * analyst can spot population shifts (PSI line) and operational shifts
 * (approval-rate line) on the same time axis. Mirrors how CreditVigil and
 * DMS Anolytics present drift monitoring as one panel, not two.
 *
 * Two y-axes: PSI on the left (with stable/drift reference lines), approval
 * rate as a percentage on the right.
 */
export function DriftTrendChart({ reports }: DriftTrendChartProps) {
  if (!reports.length) return null

  const data = [...reports]
    .reverse()
    .map((r) => ({
      date: r.report_date,
      psi: parseFloat((r.psi_score ?? 0).toFixed(4)),
      approval:
        r.approval_rate != null
          ? parseFloat((r.approval_rate * 100).toFixed(1))
          : null,
    }))

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Drift Trend</CardTitle>
        <CardDescription>
          Population Stability Index and approval rate across reporting periods
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={350}>
          <LineChart data={data} margin={{ top: 10, right: 40, bottom: 30, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            >
              <Label
                value="Report Date"
                position="bottom"
                offset={10}
                style={{ fontSize: 12, fill: '#6b7280' }}
              />
            </XAxis>
            <YAxis
              yAxisId="psi"
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            >
              <Label
                value="PSI Score"
                angle={-90}
                position="left"
                offset={0}
                style={{ fontSize: 12, fill: '#6b7280', textAnchor: 'middle' }}
              />
            </YAxis>
            <YAxis
              yAxisId="approval"
              orientation="right"
              domain={[0, 100]}
              tick={{ fontSize: 11 }}
              tickLine={{ stroke: '#d1d5db' }}
            >
              <Label
                value="Approval %"
                angle={90}
                position="right"
                offset={10}
                style={{ fontSize: 12, fill: '#6b7280', textAnchor: 'middle' }}
              />
            </YAxis>
            <Tooltip />
            <Legend
              verticalAlign="top"
              height={36}
              wrapperStyle={{ fontSize: 11, paddingBottom: 8 }}
            />
            <ReferenceLine
              yAxisId="psi"
              y={PSI_STABLE}
              stroke="#eab308"
              strokeDasharray="5 5"
              label={{
                value: PSI_STABLE.toFixed(2),
                position: 'right',
                fontSize: 10,
                fill: '#eab308',
              }}
            />
            <ReferenceLine
              yAxisId="psi"
              y={PSI_DRIFT}
              stroke="#ef4444"
              strokeDasharray="5 5"
              label={{
                value: PSI_DRIFT.toFixed(2),
                position: 'right',
                fontSize: 10,
                fill: '#ef4444',
              }}
            />
            <Line
              yAxisId="psi"
              type="monotone"
              dataKey="psi"
              name="PSI"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={{ r: 3, fill: 'hsl(var(--primary))' }}
            />
            <Line
              yAxisId="approval"
              type="monotone"
              dataKey="approval"
              name="Approval rate (%)"
              stroke="#10b981"
              strokeWidth={2}
              dot={{ r: 3, fill: '#10b981' }}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
