'use client'

import { CheckCircle, XCircle, AlertTriangle, Activity } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface PipelineStatsProps {
  pipeline: {
    total: number
    completed: number
    failed: number
    escalated: number
    success_rate: number
  }
}

export function PipelineStats({ pipeline }: PipelineStatsProps) {
  const items = [
    {
      label: 'Total Runs',
      value: pipeline.total,
      icon: Activity,
      color: 'text-blue-600',
      bg: 'bg-blue-50',
    },
    {
      label: 'Completed',
      value: pipeline.completed,
      icon: CheckCircle,
      color: 'text-emerald-600',
      bg: 'bg-emerald-50',
    },
    {
      label: 'Failed',
      value: pipeline.failed,
      icon: XCircle,
      color: 'text-red-600',
      bg: 'bg-red-50',
    },
    {
      label: 'Escalated',
      value: pipeline.escalated,
      icon: AlertTriangle,
      color: 'text-amber-600',
      bg: 'bg-amber-50',
    },
  ]

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Pipeline Performance</CardTitle>
          <span className="text-sm font-semibold text-emerald-600">
            {pipeline.success_rate}% success rate
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {items.map((item) => (
            <div key={item.label} className="flex items-center gap-3">
              <div className={`rounded-lg ${item.bg} p-2`}>
                <item.icon className={`h-4 w-4 ${item.color}`} />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">{item.label}</p>
                <p className="text-lg font-bold">{item.value}</p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
