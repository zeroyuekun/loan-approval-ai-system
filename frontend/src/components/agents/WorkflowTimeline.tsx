'use client'

import { AgentStep } from '@/types'
import { CheckCircle, Loader2, XCircle, Circle } from 'lucide-react'

interface WorkflowTimelineProps {
  steps: AgentStep[]
}

function getStepIcon(status: AgentStep['status']) {
  switch (status) {
    case 'completed':
      return <CheckCircle className="h-5 w-5 text-green-600" />
    case 'running':
      return <Loader2 className="h-5 w-5 text-blue-600 animate-spin" />
    case 'failed':
      return <XCircle className="h-5 w-5 text-red-600" />
    default:
      return <Circle className="h-5 w-5 text-gray-400" />
  }
}

function getLineColor(status: AgentStep['status']): string {
  switch (status) {
    case 'completed':
      return 'bg-green-300'
    case 'running':
      return 'bg-blue-300'
    case 'failed':
      return 'bg-red-300'
    default:
      return 'bg-gray-200'
  }
}

function getDuration(step: AgentStep): string | null {
  if (!step.started_at || !step.completed_at) return null
  const start = new Date(step.started_at).getTime()
  const end = new Date(step.completed_at).getTime()
  const ms = end - start
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function WorkflowTimeline({ steps }: WorkflowTimelineProps) {
  return (
    <div className="space-y-0">
      {steps.map((step, index) => (
        <div key={index} className="flex gap-3">
          <div className="flex flex-col items-center">
            {getStepIcon(step.status)}
            {index < steps.length - 1 && (
              <div className={`w-0.5 flex-1 min-h-[2rem] ${getLineColor(step.status)}`} />
            )}
          </div>
          <div className="pb-6 flex-1">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium">{step.step_name}</p>
              {getDuration(step) && (
                <span className="text-xs text-muted-foreground">({getDuration(step)})</span>
              )}
            </div>
            {step.result_summary && (
              <p className="text-sm text-muted-foreground mt-0.5">{step.result_summary}</p>
            )}
            {step.error && (
              <p className="text-sm text-destructive mt-0.5">{step.error}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
