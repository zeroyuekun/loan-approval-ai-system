'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { LoanApplication, GeneratedEmail, AgentRun } from '@/types'
import { usePipelineOrchestration } from '@/hooks/usePipelineOrchestration'
import { ApplicationHeader } from '@/components/applications/ApplicationHeader'
import { FinancialDetails } from '@/components/applications/FinancialDetails'
import { CreditProfile } from '@/components/applications/CreditProfile'
import { DecisionSection } from '@/components/applications/DecisionSection'
import { PipelineControls } from '@/components/applications/PipelineControls'
import { WorkflowTimeline } from '@/components/agents/WorkflowTimeline'
import { NextBestOfferCard } from '@/components/agents/NextBestOfferCard'
import { MarketingEmailCard } from '@/components/agents/MarketingEmailCard'
import { EmailPreview } from '@/components/emails/EmailPreview'
import { BiasScoreBadge } from '@/components/emails/BiasScoreBadge'
import { RepaymentCalculator } from '@/components/applications/RepaymentCalculator'
import { Button } from '@/components/ui/button'
import { loansApi } from '@/lib/api'
import { Download } from 'lucide-react'

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
  const pipeline = usePipelineOrchestration(application.id, agentRunProp, onRefresh)
  const agentRun = pipeline.agentRun

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
        <ApplicationHeader application={application} />
        <FinancialDetails application={application} />
      </div>

      {/* Credit Profile */}
      <CreditProfile application={application} />

      {/* Actions */}
      <PipelineControls
        applicationStatus={application.status}
        orchestrating={pipeline.orchestrating}
        pipelineQueued={pipeline.pipelineQueued}
        pipelineDisabled={pipeline.pipelineDisabled}
        pipelineError={pipeline.pipelineError}
        pipelineSuccess={pipeline.pipelineSuccess}
        handleOrchestrate={pipeline.handleOrchestrate}
        onDelete={onDelete}
        isDeleting={isDeleting}
        showDeleteConfirm={showDeleteConfirm}
        onDeleteConfirmToggle={onDeleteConfirmToggle}
      />

      {/* ML Decision */}
      {decision && <DecisionSection decision={decision} />}

      {/* Decision Letter Download */}
      {decision && (
        <Button
          variant="outline"
          size="sm"
          onClick={async () => {
            try {
              const { data } = await loansApi.downloadDecisionLetter(application.id)
              const url = URL.createObjectURL(data as Blob)
              const a = document.createElement('a')
              a.href = url
              a.download = `decision-letter-${application.id}.pdf`
              a.click()
              URL.revokeObjectURL(url)
            } catch {
              // error is handled by the API interceptor toast
            }
          }}
        >
          <Download className="mr-2 h-4 w-4" />
          Download Decision Letter
        </Button>
      )}

      {/* Repayment Calculator */}
      <RepaymentCalculator
        loanAmount={application.loan_amount}
        loanTermMonths={application.loan_term_months}
      />

      {/* Generated Email */}
      {email && <EmailPreview email={email} />}

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
          <h3 className="text-lg font-semibold">Marketing Email</h3>
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
