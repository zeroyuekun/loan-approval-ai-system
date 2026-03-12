'use client'

import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { AgentRun, PaginatedResponse } from '@/types'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { WorkflowTimeline } from '@/components/agents/WorkflowTimeline'
import { AgentStepCard } from '@/components/agents/AgentStepCard'
import { NextBestOfferCard } from '@/components/agents/NextBestOfferCard'
import { formatDate, getStatusColor } from '@/lib/utils'
import { Bot } from 'lucide-react'

export default function AgentsPage() {
  const { data, isLoading } = useQuery<PaginatedResponse<AgentRun>>({
    queryKey: ['agentRuns'],
    queryFn: async () => {
      const { data } = await api.get('/agents/runs/')
      return data
    },
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-48" />
        ))}
      </div>
    )
  }

  const runs = data?.results || []

  if (runs.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <Bot className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No agent workflows yet</p>
          <p className="text-sm text-muted-foreground">
            Agent workflows are triggered when you run the AI pipeline on a loan application
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {runs.map((run) => (
        <Card key={run.id}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base">
                  Agent Run - Application {run.application.slice(0, 8)}
                </CardTitle>
                <CardDescription>
                  {formatDate(run.created_at)}
                  {run.total_time_ms && ` - ${(run.total_time_ms / 1000).toFixed(1)}s total`}
                </CardDescription>
              </div>
              <Badge className={getStatusColor(run.status)} variant="outline">
                {run.status}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Timeline */}
            {run.steps.length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-3">Workflow Steps</h4>
                <WorkflowTimeline steps={run.steps} />
              </div>
            )}

            {/* Step Details */}
            {run.steps.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-sm font-medium">Step Details</h4>
                {run.steps.map((step, index) => (
                  <AgentStepCard key={index} step={step} />
                ))}
              </div>
            )}

            {/* Next Best Offers */}
            {run.next_best_offers && run.next_best_offers.length > 0 && (
              <div className="space-y-2">
                {run.next_best_offers.map((offer) => (
                  <NextBestOfferCard key={offer.id} offer={offer} />
                ))}
              </div>
            )}

            {/* Error */}
            {run.error && (
              <div className="rounded-md bg-destructive/10 p-3">
                <p className="text-sm text-destructive">{run.error}</p>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
