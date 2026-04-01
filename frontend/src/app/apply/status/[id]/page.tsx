'use client'

import { useEffect } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useApplication } from '@/hooks/useApplications'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft, CheckCircle2, XCircle, Clock, AlertCircle, Loader2, AlertTriangle } from 'lucide-react'
import { formatCurrency, formatDate, getDisplayStatus } from '@/lib/utils'

const statusIcons: Record<string, React.ReactNode> = {
  pending: <Clock className="h-8 w-8 text-yellow-500" />,
  processing: <Clock className="h-8 w-8 text-blue-500 animate-pulse" />,
  approved: <CheckCircle2 className="h-8 w-8 text-green-500" />,
  denied: <XCircle className="h-8 w-8 text-red-500" />,
  review: <AlertCircle className="h-8 w-8 text-purple-500" />,
}

const statusMessages: Record<string, string> = {
  pending: 'Your application has been received and is awaiting review.',
  processing: 'Your application is currently being assessed by our AI system.',
  approved: 'Congratulations! Your loan application has been approved.',
  denied: 'Unfortunately, your loan application was not approved at this time.',
  review: 'Your application has been flagged for additional review by a loan officer.',
}

interface PipelineStep {
  label: string
  state: 'completed' | 'active' | 'upcoming'
}

function getPipelineSteps(status: string): PipelineStep[] {
  const steps: PipelineStep[] = [
    { label: 'Submitted', state: 'upcoming' },
    { label: 'Assessing', state: 'upcoming' },
    { label: 'Decision', state: 'upcoming' },
    { label: 'Complete', state: 'upcoming' },
  ]

  switch (status) {
    case 'pending':
      steps[0].state = 'completed'
      steps[1].state = 'upcoming'
      break
    case 'processing':
      steps[0].state = 'completed'
      steps[1].state = 'active'
      break
    case 'review':
      steps[0].state = 'completed'
      steps[1].state = 'completed'
      steps[2].state = 'active'
      break
    case 'denied':
      steps[0].state = 'completed'
      steps[1].state = 'completed'
      steps[2].state = 'completed'
      break
    case 'approved':
      steps[0].state = 'completed'
      steps[1].state = 'completed'
      steps[2].state = 'completed'
      steps[3].state = 'completed'
      break
    default:
      steps[0].state = 'completed'
  }

  return steps
}

function StatusPipeline({ status }: { status: string }) {
  const steps = getPipelineSteps(status)

  return (
    <div className="w-full" role="group" aria-label="Application progress">
      {/* Horizontal layout (sm and above) */}
      <div className="hidden sm:flex items-start justify-between">
        {steps.map((step, index) => (
          <div key={step.label} className="flex flex-1 items-start">
            <div className="flex flex-col items-center flex-1">
              {/* Circle */}
              <div
                className={`
                  relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold transition-all
                  ${step.state === 'completed'
                    ? 'border-green-500 bg-green-500 text-white'
                    : step.state === 'active'
                      ? 'border-blue-500 bg-blue-500 text-white animate-pulse'
                      : 'border-muted-foreground/30 bg-background text-muted-foreground/50'
                  }
                `}
              >
                {step.state === 'completed' ? (
                  <CheckCircle2 className="h-5 w-5" />
                ) : (
                  <span>{index + 1}</span>
                )}
              </div>
              {/* Label */}
              <span
                className={`mt-2 text-xs font-medium text-center ${
                  step.state === 'completed'
                    ? 'text-green-600 dark:text-green-400'
                    : step.state === 'active'
                      ? 'text-blue-600 dark:text-blue-400'
                      : 'text-muted-foreground/50'
                }`}
              >
                {step.label}
              </span>
            </div>
            {/* Connector line */}
            {index < steps.length - 1 && (
              <div className="flex items-center h-10 flex-1 max-w-[80px] mx-[-4px]">
                <div
                  className={`h-0.5 w-full ${
                    steps[index + 1].state === 'completed' || steps[index + 1].state === 'active'
                      ? 'bg-green-500'
                      : 'bg-muted-foreground/20'
                  }`}
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Vertical layout (mobile) */}
      <div className="flex sm:hidden flex-col gap-0">
        {steps.map((step, index) => (
          <div key={step.label} className="flex items-start gap-3">
            {/* Circle + connector column */}
            <div className="flex flex-col items-center">
              <div
                className={`
                  flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold
                  ${step.state === 'completed'
                    ? 'border-green-500 bg-green-500 text-white'
                    : step.state === 'active'
                      ? 'border-blue-500 bg-blue-500 text-white animate-pulse'
                      : 'border-muted-foreground/30 bg-background text-muted-foreground/50'
                  }
                `}
              >
                {step.state === 'completed' ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  <span>{index + 1}</span>
                )}
              </div>
              {index < steps.length - 1 && (
                <div
                  className={`w-0.5 h-6 ${
                    steps[index + 1].state === 'completed' || steps[index + 1].state === 'active'
                      ? 'bg-green-500'
                      : 'bg-muted-foreground/20'
                  }`}
                />
              )}
            </div>
            {/* Label */}
            <span
              className={`pt-1.5 text-sm font-medium ${
                step.state === 'completed'
                  ? 'text-green-600 dark:text-green-400'
                  : step.state === 'active'
                    ? 'text-blue-600 dark:text-blue-400'
                    : 'text-muted-foreground/50'
              }`}
            >
              {step.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function CustomerApplicationStatusPage() {
  const { id } = useParams<{ id: string }>()
  const { data: application, isLoading, refetch } = useApplication(id)

  // Poll every 5 seconds while the application is still being processed
  useEffect(() => {
    if (!application) return
    if (application.status === 'pending' || application.status === 'processing') {
      const interval = setInterval(() => {
        refetch()
      }, 5000)
      return () => clearInterval(interval)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- poll restart depends only on status change, not full application object
  }, [application?.status, refetch])

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (!application) {
    return (
      <div className="text-center py-16">
        <p className="text-lg text-muted-foreground">Application not found.</p>
        <Button asChild variant="link" className="mt-4">
          <Link href="/apply">Back to My Applications</Link>
        </Button>
      </div>
    )
  }

  const decision = application.decision
  const hasConditions =
    application.status === 'approved' &&
    Array.isArray(application.conditions) &&
    application.conditions.length > 0

  return (
    <div className="space-y-6">
      {/* Status Pipeline */}
      <Card>
        <CardContent className="py-6 px-6">
          <StatusPipeline status={application.status} />
        </CardContent>
      </Card>

      {/* Status Banner */}
      <Card>
        <CardContent className="flex items-center gap-6 py-8">
          {statusIcons[application.status] || statusIcons.pending}
          <div>
            <h2 className="text-xl font-bold capitalize mb-1">{application.purpose} Loan</h2>
            <div aria-live="polite" aria-atomic="true">
              <div className="flex items-center gap-3 mb-1">
                {(() => { const s = getDisplayStatus(application.status, application.decision); return (
                  <Badge className={s.color} variant="outline" role="status" aria-label={`Application status: ${s.label}`}>{s.label}</Badge>
                ) })()}
              </div>
              <p className="text-muted-foreground">
                {statusMessages[application.status] || 'Status unknown.'}
              </p>
            </div>
            {(application.status === 'pending' || application.status === 'processing') && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground mt-2">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Your application is being assessed by our AI system...
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Conditional Approval Alert */}
      {hasConditions && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-500/40 dark:bg-amber-950/30 p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-amber-800 dark:text-amber-300">
                Conditional Approval
              </h3>
              <p className="text-sm text-amber-700 dark:text-amber-400/90">
                Your approval is subject to the following conditions being satisfied:
              </p>
              <ul className="list-disc list-inside space-y-1">
                {application.conditions.map((condition, idx) => (
                  <li
                    key={idx}
                    className="text-sm text-amber-700 dark:text-amber-400/80"
                  >
                    {condition}
                  </li>
                ))}
              </ul>
              {application.conditions_met && (
                <p className="text-sm font-medium text-green-700 dark:text-green-400 mt-2">
                  All conditions have been satisfied.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Application Summary */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Application Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Application ID</span>
              <span className="font-mono text-sm">{application.id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Submitted</span>
              <span>{formatDate(application.created_at)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Purpose</span>
              <span className="capitalize">{application.purpose}</span>
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

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Financial Summary</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Loan Amount</span>
              <span className="font-semibold">{formatCurrency(application.loan_amount)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Loan Term</span>
              <span>{application.loan_term_months} months</span>
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
              <span className="text-muted-foreground">DTI Ratio</span>
              <span>{Number(application.debt_to_income).toFixed(1)}x</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Notes */}
      {application.notes && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Your Notes</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{application.notes}</p>
          </CardContent>
        </Card>
      )}

      <div className="flex justify-end mt-4">
        <Button asChild>
          <Link href="/apply">Finished</Link>
        </Button>
      </div>
    </div>
  )
}
