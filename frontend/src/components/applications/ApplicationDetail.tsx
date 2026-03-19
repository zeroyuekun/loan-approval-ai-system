'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { LoanApplication, GeneratedEmail, AgentRun } from '@/types'
import { formatCurrency, formatDate, formatPercent, getStatusColor } from '@/lib/utils'
import { useOrchestrate, useAgentRun } from '@/hooks/useAgentStatus'
import { WorkflowTimeline } from '@/components/agents/WorkflowTimeline'
import { NextBestOfferCard } from '@/components/agents/NextBestOfferCard'
import { MarketingEmailCard } from '@/components/agents/MarketingEmailCard'
import { EmailPreview } from '@/components/emails/EmailPreview'
import { BiasScoreBadge } from '@/components/emails/BiasScoreBadge'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import { Bot, Loader2, Trash2 } from 'lucide-react'

interface ApplicationDetailProps {
  application: LoanApplication
  email?: GeneratedEmail | null
  agentRun?: AgentRun | null
  isLoading?: boolean
  onRefresh?: () => void
  onDelete?: () => void
  isDeleting?: boolean
  showDeleteConfirm?: boolean
  onDeleteConfirmToggle?: (show: boolean) => void
}

export function ApplicationDetail({ application, email, agentRun: agentRunProp, isLoading, onRefresh, onDelete, isDeleting, showDeleteConfirm, onDeleteConfirmToggle }: ApplicationDetailProps) {
  const orchestrate = useOrchestrate()
  const [orchestrating, setOrchestrating] = useState(false)
  const [pipelineQueued, setPipelineQueued] = useState(false)
  const [preRunAgentId, setPreRunAgentId] = useState<string | null>(null)
  const [pipelineError, setPipelineError] = useState<string | null>(null)

  // Fetch agent run with polling awareness — keeps polling while pipeline is queued
  const { data: agentRunFetched } = useAgentRun(application.id, { pipelineQueued })
  // Prefer the internally fetched run (which has polling), fall back to prop
  const agentRun = agentRunFetched ?? agentRunProp ?? null

  // Reset pipelineQueued only when a NEW agent run (different ID from
  // the one present when we clicked) reaches a terminal status.
  // This prevents the old completed run from immediately clearing the
  // queued state before Celery creates the new AgentRun.
  useEffect(() => {
    if (!pipelineQueued || !agentRun) return
    const isNewRun = agentRun.id !== preRunAgentId
    const isTerminal = ['completed', 'failed', 'escalated'].includes(agentRun.status)
    if (isNewRun && isTerminal) {
      setPipelineQueued(false)
      setPreRunAgentId(null)
      // Refresh email + application data now that the pipeline finished
      onRefresh?.()
    }
  }, [agentRun?.id, agentRun?.status, pipelineQueued, preRunAgentId, onRefresh])

  // Safety timeout: if pipelineQueued stays true for over 2 minutes,
  // force-reset so the button isn't stuck forever.
  useEffect(() => {
    if (!pipelineQueued) return
    const timer = setTimeout(() => {
      setPipelineQueued(false)
      setPreRunAgentId(null)
      setPipelineError('Pipeline timed out. Please try again.')
    }, 120_000)
    return () => clearTimeout(timer)
  }, [pipelineQueued])

  const handleOrchestrate = async () => {
    setOrchestrating(true)
    setPipelineError(null)
    // Snapshot the current agent run ID so we can detect when a new one appears
    setPreRunAgentId(agentRun?.id ?? null)
    try {
      await orchestrate.mutateAsync(application.id)
      setPipelineQueued(true)
      onRefresh?.()
    } catch (error: any) {
      console.error('Orchestration failed:', error)
      setPipelineError(error?.message || 'Pipeline failed to start. Please try again.')
      setPreRunAgentId(null)
    } finally {
      setOrchestrating(false)
    }
  }

  const pipelineDisabled = orchestrating || pipelineQueued

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
              <Link href={`/dashboard/customers/${application.applicant.id}`} className="text-blue-600 hover:underline">
                {application.applicant.first_name} {application.applicant.last_name}
              </Link>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Status</span>
              <Badge className={getStatusColor(application.status)} variant="outline">
                {application.status.toUpperCase()}
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
              <span>{Number(application.debt_to_income).toFixed(1)}x</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Employment</span>
              <span className="capitalize">{application.employment_type?.replace(/_/g, ' ') || '—'} ({application.employment_length} yrs)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Applicant Type</span>
              <span className="capitalize">{application.applicant_type} ({application.number_of_dependants} dependants)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Monthly Expenses</span>
              <span>{application.monthly_expenses != null ? formatCurrency(application.monthly_expenses) : '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Credit Card Limit</span>
              <span>{formatCurrency(application.existing_credit_card_limit)}</span>
            </div>
            {application.purpose === 'home' && application.property_value != null && (
              <>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Property Value</span>
                  <span>{formatCurrency(application.property_value)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Deposit</span>
                  <span>{application.deposit_amount != null ? formatCurrency(application.deposit_amount) : '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">LVR</span>
                  <span>{application.property_value > 0 ? `${((application.loan_amount / application.property_value) * 100).toFixed(1)}%` : '—'}</span>
                </div>
              </>
            )}
            <div className="flex justify-between">
              <span className="text-muted-foreground">Home Ownership</span>
              <span className="capitalize">{application.home_ownership}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Co-signer</span>
              <span>{application.has_cosigner ? 'Yes' : 'No'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">HECS/HELP Debt</span>
              <span>{application.has_hecs ? 'Yes' : 'No'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Bankruptcy History</span>
              <span>{application.has_bankruptcy ? 'Yes' : 'No'}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Actions */}
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-6">
          <div className="flex items-center justify-center gap-4">
            <Button
              size="lg"
              onClick={handleOrchestrate}
              disabled={pipelineDisabled}
              variant={pipelineQueued ? 'outline' : 'default'}
            >
              {orchestrating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Running AI Pipeline...
                </>
              ) : pipelineQueued ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Pipeline Queued — Processing...
                </>
              ) : (
                <>
                  <Bot className="mr-2 h-4 w-4" />
                  {application.status === 'pending' ? 'Run AI Pipeline' : 'Re-run AI Pipeline'}
                </>
              )}
            </Button>
            {onDelete && (
            !showDeleteConfirm ? (
              <Button
                variant="destructive"
                size="lg"
                onClick={() => onDeleteConfirmToggle?.(true)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete Application
              </Button>
            ) : (
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-red-600">Are you sure?</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onDeleteConfirmToggle?.(false)}
                  disabled={isDeleting}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={onDelete}
                  disabled={isDeleting}
                >
                  {isDeleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                  {isDeleting ? 'Deleting...' : 'Confirm'}
                </Button>
              </div>
            )
          )}
          </div>
          {pipelineError && (
            <p className="text-sm text-red-600">{pipelineError}</p>
          )}
        </CardContent>
      </Card>

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
              {decision.risk_score != null && (
                <span className="text-sm text-muted-foreground">
                  Risk Score: {Number(decision.risk_score).toFixed(2)}
                </span>
              )}
            </div>
            <p className="text-sm">{decision.reasoning}</p>
            {decision.feature_importances && (Array.isArray(decision.feature_importances) ? decision.feature_importances.length > 0 : Object.keys(decision.feature_importances).length > 0) && (
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
            <CardDescription>
              Compliance checks run on each generated email. A score of 0 means all deterministic checks passed
              with no prohibited language, tone issues, or bias detected. Non-zero scores appear when
              pattern-matching flags potential violations (e.g. discriminatory language, pressure tactics).
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {agentRun.bias_reports.map((report) => (
              <div key={report.id} className="rounded-lg border p-4 space-y-3">
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="outline" className={
                    report.report_type === 'decision'
                      ? 'bg-blue-50 text-blue-700 border-blue-200'
                      : 'bg-purple-50 text-purple-700 border-purple-200'
                  }>
                    {report.report_type === 'decision' ? 'Decision Email' : 'Marketing Email'}
                  </Badge>
                  {report.score_source && (
                    <span className="text-xs text-muted-foreground">
                      Source: {report.score_source.replace(/_/g, ' ')}
                    </span>
                  )}
                </div>
                <div className="flex items-start gap-4">
                  <BiasScoreBadge score={report.bias_score} categories={report.categories} />
                  <div className="flex-1">
                    <p className="text-sm">{report.analysis}</p>
                    {report.deterministic_score != null && (
                      <p className="text-xs text-muted-foreground mt-1">
                        Deterministic score: {report.deterministic_score}/100
                      </p>
                    )}
                    {report.requires_human_review && (
                      <Badge variant="destructive" className="mt-2">Requires Human Review</Badge>
                    )}
                    {report.ai_review_approved !== null && (
                      <div className="mt-2 space-y-1">
                        <Badge variant={report.ai_review_approved ? 'default' : 'destructive'}>
                          AI Review: {report.ai_review_approved ? 'Approved' : 'Flagged for Human Review'}
                        </Badge>
                        {report.ai_review_reasoning && (
                          <p className="text-xs text-muted-foreground">{report.ai_review_reasoning}</p>
                        )}
                      </div>
                    )}
                  </div>
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

      {/* Marketing Follow-up Email */}
      {agentRun?.marketing_emails && agentRun.marketing_emails.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Marketing Agent</h3>
          {agentRun.marketing_emails.map((me) => (
            <MarketingEmailCard key={me.id} email={me} />
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
