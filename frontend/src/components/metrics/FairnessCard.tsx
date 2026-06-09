'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Label } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { useChartHover, ChartHoverPanel, renderEmptyTooltip } from './ChartHoverPanel'

interface FairnessCardProps {
  fairnessMetrics: Record<string, any>
}

type GroupStats = {
  count: number
  actual_approval_rate: number
  predicted_approval_rate: number
  tpr: number
  fpr: number
  included_in_fairness?: boolean
}

// Title-case a label while preserving existing capitals: "self_employed" -> "Self Employed",
// "payg casual" -> "Payg Casual", and already-uppercase codes like "NSW"/"NT" stay intact.
const titleCase = (s: string) => s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

function FairnessAttributeCard({ attribute, data }: { attribute: string; data: any }) {
  const { active, hoverProps } = useChartHover()
  if (!data?.groups) return null

  const groups = data.groups as Record<string, GroupStats>
  // The backend emits disparate_impact_ratio / passes_80_percent_rule as null when
  // fewer than two groups are large enough to assess (or there are no approvals at
  // all). When that's the case we hide the Equalized Odds figure rather than show a
  // coerced 0.0000 — an un-measurable fairness result must never read as a clean
  // pass on a regulated lending dashboard.
  const assessable: boolean =
    typeof data.disparate_impact_ratio === 'number' && typeof data.passes_80_percent_rule === 'boolean'
  const eqOddsDiff: number | null =
    assessable && typeof data.equalized_odds_difference === 'number' ? data.equalized_odds_difference : null
  const minGroupSize: number = data.min_group_size ?? 30
  const excludedGroups: string[] = Array.isArray(data.excluded_small_groups) ? data.excluded_small_groups : []

  const chartData = Object.entries(groups).map(([group, vals]) => ({
    group: titleCase(group) + (vals.included_in_fairness === false ? ' *' : ''),
    'Actual Approval': parseFloat((vals.actual_approval_rate * 100).toFixed(1)),
    'Predicted Approval': parseFloat((vals.predicted_approval_rate * 100).toFixed(1)),
    TPR: parseFloat((vals.tpr * 100).toFixed(1)),
    FPR: parseFloat((vals.fpr * 100).toFixed(1)),
    count: vals.count,
  }))

  const label = titleCase(attribute)

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Fairness: {label}</CardTitle>
        <CardDescription className="mt-1.5">
          Equalized Odds Diff: {eqOddsDiff !== null ? eqOddsDiff.toFixed(4) : '—'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={chartData} margin={{ top: 10, right: 20, bottom: 30, left: 10 }} {...hoverProps}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
            <XAxis
              dataKey="group"
              tick={{ fontSize: 10 }}
              interval={0}
              angle={-25}
              textAnchor="end"
              height={60}
              tickLine={{ stroke: '#d1d5db' }}
            />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }}>
              <Label value="%" angle={-90} position="insideLeft" offset={10} style={{ fontSize: 12, fill: '#6b7280', textAnchor: 'middle' }} />
            </YAxis>
            <Tooltip content={renderEmptyTooltip} />
            <Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
            <Bar dataKey="Actual Approval" fill="#60a5fa" radius={[4, 4, 0, 0]} />
            <Bar dataKey="Predicted Approval" fill="#34d399" radius={[4, 4, 0, 0]} />
            <Bar dataKey="TPR" fill="#a78bfa" radius={[4, 4, 0, 0]} />
            <Bar dataKey="FPR" fill="#fb923c" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <ChartHoverPanel active={active} formatValue={(v) => `${v}%`} />
        {excludedGroups.length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            <span aria-hidden>* </span>
            {excludedGroups.length} small group{excludedGroups.length === 1 ? '' : 's'} (
            {excludedGroups.map(titleCase).join(', ')}) excluded from the
            disparate-impact ratio — fewer than {minGroupSize} samples to assess reliably. Still
            shown above for transparency.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function FairnessCard({ fairnessMetrics }: FairnessCardProps) {
  if (!fairnessMetrics || Object.keys(fairnessMetrics).length === 0) return null

  return (
    <div className="space-y-6">
      {Object.entries(fairnessMetrics).map(([attribute, data]) => (
        <FairnessAttributeCard key={attribute} attribute={attribute} data={data} />
      ))}
    </div>
  )
}
