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

function formatNumber(n: number): string {
  return n.toLocaleString()
}

function TokenUsageDisplay({ summary }: { summary: any }) {
  if (!summary || typeof summary !== 'object') return null

  const inputTokens = summary.input_tokens as number | undefined
  const outputTokens = summary.output_tokens as number | undefined
  const totalTokens = summary.total_tokens as number | undefined
  const genTime = summary.generation_time_ms as number | undefined

  const hasTokens = inputTokens != null || outputTokens != null || totalTokens != null

  if (!hasTokens) return null

  return (
    <div className="flex flex-wrap items-center gap-3 mt-3 pt-3 border-t border-border/40">
      {totalTokens != null && (
        <span className="text-xs text-muted-foreground flex items-center gap-1">
          <span aria-hidden>&#x1f524;</span> {formatNumber(totalTokens)} tokens
        </span>
      )}
      {inputTokens != null && totalTokens == null && (
        <span className="text-xs text-muted-foreground flex items-center gap-1">
          <span aria-hidden>&#x2B07;&#xFE0F;</span> {formatNumber(inputTokens)} in
        </span>
      )}
      {outputTokens != null && totalTokens == null && (
        <span className="text-xs text-muted-foreground flex items-center gap-1">
          <span aria-hidden>&#x2B06;&#xFE0F;</span> {formatNumber(outputTokens)} out
        </span>
      )}
      {inputTokens != null && outputTokens != null && totalTokens != null && (
        <span className="text-xs text-muted-foreground">
          ({formatNumber(inputTokens)} in / {formatNumber(outputTokens)} out)
        </span>
      )}
      {genTime != null && (
        <span className="text-xs text-muted-foreground flex items-center gap-1">
          <span aria-hidden>&#x23F1;&#xFE0F;</span>
          {genTime < 1000 ? `${genTime}ms` : `${(genTime / 1000).toFixed(1)}s`}
        </span>
      )}
    </div>
  )
}

function PredictionDisplay({ summary, stepName }: { summary: any; stepName: string }) {
  if (!summary || typeof summary !== 'object') return null
  if (stepName !== 'ml_prediction' && stepName !== 'fraud_check') return null

  const prediction = summary.prediction as string | undefined
  const probability = summary.probability as number | undefined

  if (!prediction && probability == null) return null

  const isApproved = prediction?.toLowerCase() === 'approved'
  const isDenied = prediction?.toLowerCase() === 'denied'

  return (
    <div className="flex items-center gap-3 mt-3 pt-3 border-t border-border/40">
      {prediction && (
        <Badge
          variant="outline"
          className={
            isApproved
              ? 'bg-green-500/10 text-green-400 border-green-500/30'
              : isDenied
              ? 'bg-red-500/10 text-red-400 border-red-500/30'
              : 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30'
          }
        >
          {prediction.charAt(0).toUpperCase() + prediction.slice(1)}
        </Badge>
      )}
      {probability != null && (
        <span className="text-xs text-muted-foreground">
          Confidence: <span className="font-medium text-foreground/80">{(probability * 100).toFixed(1)}%</span>
        </span>
      )}
    </div>
  )
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
          <TokenUsageDisplay summary={step.result_summary} />
          <PredictionDisplay summary={step.result_summary} stepName={step.step_name} />
        </CardContent>
      )}
    </Card>
  )
}
