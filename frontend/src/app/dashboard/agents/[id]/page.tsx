'use client'

import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { authApi } from '@/lib/api'
import { CustomerActivity, AgentRun } from '@/types'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { WorkflowTimeline } from '@/components/agents/WorkflowTimeline'
import { AgentStepCard } from '@/components/agents/AgentStepCard'
import { NextBestOfferCard } from '@/components/agents/NextBestOfferCard'
import { MarketingEmailCard } from '@/components/agents/MarketingEmailCard'
import { PipelineSummaryBar } from '@/components/agents/PipelineSummaryBar'
import { StepLatencyChart } from '@/components/agents/StepLatencyChart'
import { formatDate, getStatusColor } from '@/lib/utils'
import { ArrowLeft, Bot, FileText, ChevronRight } from 'lucide-react'

interface ApplicationGroup {
  application_id: string
  runs: AgentRun[]
  latestDate: string
  completedCount: number
  failedCount: number
}

function groupByApplication(runs: AgentRun[]): ApplicationGroup[] {
  const map = new Map<string, ApplicationGroup>()
  for (const run of runs) {
    const appId = run.application_id
    if (!map.has(appId)) {
      map.set(appId, { application_id: appId, runs: [], latestDate: run.created_at, completedCount: 0, failedCount: 0 })
    }
    const group = map.get(appId)!
    group.runs.push(run)
    if (run.status === 'completed') group.completedCount++
    if (run.status === 'failed') group.failedCount++
    if (run.created_at > group.latestDate) group.latestDate = run.created_at
  }
  // Sort by latest date descending
  return Array.from(map.values()).sort((a, b) => b.latestDate.localeCompare(a.latestDate))
}

function RunCard({ run }: { run: AgentRun }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">
              Run {run.id.slice(0, 8)}
            </CardTitle>
            <CardDescription>
              {formatDate(run.created_at)}
              {run.total_time_ms && ` · ${(run.total_time_ms / 1000).toFixed(1)}s total`}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {run.total_input_tokens != null && run.total_output_tokens != null && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {((run.total_input_tokens ?? 0) + (run.total_output_tokens ?? 0)).toLocaleString()} tokens
              </span>
            )}
            <Badge className={getStatusColor(run.status)} variant="outline">
              {run.status.toUpperCase()}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {run.steps.length > 0 && (
          <div>
            <PipelineSummaryBar steps={run.steps} />
            <h4 className="text-sm font-medium mb-3">Workflow Steps</h4>
            <WorkflowTimeline steps={run.steps} />
          </div>
        )}
        {run.steps.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium">Step Details</h4>
            {run.steps.map((step, index) => (
              <AgentStepCard key={index} step={step} />
            ))}
          </div>
        )}
        {run.steps.length >= 3 && (
          <StepLatencyChart steps={run.steps} />
        )}
        {run.next_best_offers && run.next_best_offers.length > 0 && (
          <div className="space-y-2">
            {run.next_best_offers.map((offer) => (
              <NextBestOfferCard key={offer.id} offer={offer} />
            ))}
          </div>
        )}
        {run.marketing_emails && run.marketing_emails.length > 0 && (
          <div className="space-y-2">
            {run.marketing_emails.map((email) => (
              <MarketingEmailCard key={email.id} email={email} />
            ))}
          </div>
        )}
        {run.error && (
          <div className="rounded-md bg-destructive/10 p-3">
            <p className="text-sm text-destructive">{run.error}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function CustomerAgentRunsPage() {
  const params = useParams()
  const router = useRouter()
  const customerId = Number(params.id)

  const { data: activity, isLoading } = useQuery<CustomerActivity>({
    queryKey: ['customerActivity', customerId],
    queryFn: async () => {
      const { data } = await authApi.getCustomerActivity(customerId)
      return data
    },
    enabled: !isNaN(customerId),
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-48" />
        ))}
      </div>
    )
  }

  const agentRuns = activity?.agent_runs || []
  const customerName = activity?.customer_name || 'Unknown'
  const applicationGroups = groupByApplication(agentRuns)
  const hasMultipleApplications = applicationGroups.length > 1

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => router.push('/dashboard/agents')}
          className="rounded-lg p-2 hover:bg-muted transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{customerName}</h1>
          <p className="text-muted-foreground">
            {agentRuns.length} agent workflow{agentRuns.length !== 1 ? 's' : ''}
            {hasMultipleApplications && ` across ${applicationGroups.length} applications`}
          </p>
        </div>
      </div>

      {agentRuns.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Bot className="h-10 w-10 mb-3" />
            <p>No agent workflows for this client yet</p>
          </CardContent>
        </Card>
      ) : hasMultipleApplications ? (
        // Grouped by application
        applicationGroups.map((group) => (
          <div key={group.application_id} className="space-y-3">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-100">
                      <FileText className="h-4 w-4 text-violet-600" />
                    </div>
                    <div>
                      <CardTitle className="text-sm flex items-center gap-2">
                        Application {group.application_id.slice(0, 8)}
                        <Link
                          href={`/dashboard/applications/${group.application_id}`}
                          className="text-xs text-blue-600 hover:underline font-normal"
                        >
                          View application
                          <ChevronRight className="inline h-3 w-3" />
                        </Link>
                      </CardTitle>
                      <CardDescription className="text-xs">
                        {group.runs.length} workflow{group.runs.length !== 1 ? 's' : ''} &middot; Last: {formatDate(group.latestDate)}
                      </CardDescription>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {group.completedCount > 0 && (
                      <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 text-xs">
                        {group.completedCount} completed
                      </Badge>
                    )}
                    {group.failedCount > 0 && (
                      <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 text-xs">
                        {group.failedCount} failed
                      </Badge>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-0 space-y-4">
                {group.runs.map((run) => (
                  <RunCard key={run.id} run={run} />
                ))}
              </CardContent>
            </Card>
          </div>
        ))
      ) : (
        // Single application — no extra grouping needed
        <div className="space-y-4">
          {agentRuns.map((run) => (
            <RunCard key={run.id} run={run} />
          ))}
        </div>
      )}
    </div>
  )
}
