'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { AgentStep } from '@/types'
import { CheckCircle, Loader2, XCircle, Circle, ChevronDown, ChevronRight } from 'lucide-react'
import { formatStepName, formatResultSummary } from './stepLabels'

interface AgentStepCardProps {
  step: AgentStep
}

function getStatusBadge(status: AgentStep['status']) {
  switch (status) {
    case 'completed':
      return <Badge className="bg-green-100 text-green-800" variant="outline"><CheckCircle className="mr-1 h-3 w-3" />Completed</Badge>
    case 'running':
      return <Badge className="bg-blue-100 text-blue-800" variant="outline"><Loader2 className="mr-1 h-3 w-3 animate-spin" />Running</Badge>
    case 'failed':
      return <Badge className="bg-red-100 text-red-800" variant="outline"><XCircle className="mr-1 h-3 w-3" />Failed</Badge>
    default:
      return <Badge className="bg-gray-100 text-gray-800" variant="outline"><Circle className="mr-1 h-3 w-3" />Pending</Badge>
  }
}

export function AgentStepCard({ step }: AgentStepCardProps) {
  const [expanded, setExpanded] = useState(false)

  const duration = step.started_at && step.completed_at
    ? `${((new Date(step.completed_at).getTime() - new Date(step.started_at).getTime()) / 1000).toFixed(1)}s`
    : null

  const summaryItems = formatResultSummary(step.result_summary)

  return (
    <Card>
      <CardHeader
        className="cursor-pointer pb-3"
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e: React.KeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setExpanded(!expanded)
          }
        }}
        aria-expanded={expanded}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            <CardTitle className="text-sm">{formatStepName(step.step_name)}</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {duration && <span className="text-xs text-muted-foreground">{duration}</span>}
            {getStatusBadge(step.status)}
          </div>
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="pt-0">
          {summaryItems.length > 0 ? (
            summaryItems.length === 1 && !summaryItems[0].label ? (
              <p className="text-sm text-muted-foreground mb-2">{summaryItems[0].value}</p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 mb-2">
                {summaryItems.map(({ label, value }) => (
                  <div key={label} className="text-sm">
                    <span className="text-muted-foreground">{label}</span>
                    <p className="font-medium">{value}</p>
                  </div>
                ))}
              </div>
            )
          ) : null}
          {step.error && (
            <div className="rounded-md bg-destructive/10 p-3">
              <p className="text-sm text-destructive">{step.error}</p>
            </div>
          )}
          {summaryItems.length === 0 && !step.error && (
            <p className="text-sm text-muted-foreground">No details available</p>
          )}
        </CardContent>
      )}
    </Card>
  )
}
