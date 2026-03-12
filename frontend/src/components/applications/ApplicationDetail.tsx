'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { LoanApplication, GeneratedEmail, AgentRun } from '@/types'
import { formatCurrency, formatDate, formatPercent, getStatusColor } from '@/lib/utils'
import { useOrchestrate } from '@/hooks/useAgentStatus'
import { WorkflowTimeline } from '@/components/agents/WorkflowTimeline'
import { NextBestOfferCard } from '@/components/agents/NextBestOfferCard'
import { EmailPreview } from '@/components/emails/EmailPreview'
import { BiasScoreBadge } from '@/components/emails/BiasScoreBadge'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import { Bot, Loader2 } from 'lucide-react'

interface ApplicationDetailProps {
  application: LoanApplication
  email?: GeneratedEmail | null
  agentRun?: AgentRun | null
  isLoading?: boolean
  onRefresh?: () => void
}

export function ApplicationDetail({ application, email, agentRun, isLoading, onRefresh }: ApplicationDetailProps) {
  const orchestrate = useOrchestrate()
  const [orchestrating, setOrchestrating] = useState(false)

  const handleOrchestrate = async () => {
    setOrchestrating(true)
    try {
      await orchestrate.mutateAsync(application.id)
      onRefresh?.()
    } catch (error) {
      console.error('Orchestration failed:', error)
    } finally {
      setOrchestrating(false)
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  const decision = application.decision

  return (
    <div className="space-y-6">
      {/* Application Info */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Application Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">ID</span>
              <span className="font-mono text-sm">{application.id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Applicant</span>
              <span>{application.applicant.first_name} {application.applicant.last_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Status</span>
              <Badge className={getStatusColor(application.status)} variant="outline">
                {application.status}
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Created</span>
              <span>{formatDate(application.created_at)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Purpose</span>
              <span className="capitalize">{application.purpose}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Financial Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Loan Amount</span>
              <span className="font-semibold">{formatCurrency(application.loan_amount)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Annual Income</span>
              <span>{formatCurrency(application.annual_income)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Credit Score</span>
              <span>{application.credit_score}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Loan Term</span>
              <span>{application.loan_term_months} months</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">DTI Ratio</span>
              <span>{application.debt_to_income}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Employment</span>
              <span>{application.employment_length} years</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Home Ownership</span>
              <span className="capitalize">{application.home_ownership}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Co-signer</span>
              <span>{application.has_cosigner ? 'Yes' : 'No'}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Run AI Pipeline Button */}
      {application.status === 'pending' && (
        <Card>
          <CardContent className="flex items-center justify-center py-8">
            <Button
              size="lg"
              onClick={handleOrchestrate}
              disabled={orchestrating}
            >
              {orchestrating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Running AI Pipeline...
                </>
              ) : (
                <>
                  <Bot className="mr-2 h-4 w-4" />
                  Run AI Pipeline
                </>
              )}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* ML Decision */}
      {decision && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">ML Decision</CardTitle>
            <CardDescription>Model: {decision.model_version}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-4">
              <Badge className={decision.decision === 'approved' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'} variant="outline">
                {decision.decision.toUpperCase()}
              </Badge>
              <span className="text-sm text-muted-foreground">
                Confidence: {formatPercent(decision.confidence)}
              </span>
              {decision.risk_score !== null && (
                <span className="text-sm text-muted-foreground">
                  Risk Score: {decision.risk_score.toFixed(2)}
                </span>
              )}
            </div>
            <p className="text-sm">{decision.reasoning}</p>
            {Object.keys(decision.feature_importances).length > 0 && (
              <FeatureImportance features={decision.feature_importances} />
            )}
          </CardContent>
        </Card>
      )}

      {/* Generated Email */}
      {email && (
        <EmailPreview email={email} />
      )}

      {/* Bias Report */}
      {agentRun?.bias_reports && agentRun.bias_reports.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Bias Analysis</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {agentRun.bias_reports.map((report) => (
              <div key={report.id} className="flex items-start gap-4">
                <BiasScoreBadge score={report.bias_score} categories={report.categories} />
                <div className="flex-1">
                  <p className="text-sm">{report.analysis}</p>
                  {report.requires_human_review && (
                    <Badge variant="destructive" className="mt-2">Requires Human Review</Badge>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Next Best Offers */}
      {agentRun?.next_best_offers && agentRun.next_best_offers.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Alternative Offers</h3>
          {agentRun.next_best_offers.map((nbo) => (
            <NextBestOfferCard key={nbo.id} offer={nbo} />
          ))}
        </div>
      )}

      {/* Agent Timeline */}
      {agentRun && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Agent Workflow Timeline</CardTitle>
            <CardDescription>
              Total time: {agentRun.total_time_ms ? `${(agentRun.total_time_ms / 1000).toFixed(1)}s` : 'In progress'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <WorkflowTimeline steps={agentRun.steps} />
          </CardContent>
        </Card>
      )}

      {/* Notes */}
      {application.notes && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Notes</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{application.notes}</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
