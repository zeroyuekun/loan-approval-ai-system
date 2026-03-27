'use client'

import { useEffect } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useApplication } from '@/hooks/useApplications'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft, CheckCircle2, XCircle, Clock, AlertCircle, Loader2 } from 'lucide-react'
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

  return (
    <div className="space-y-6">
      {/* Status Banner */}
      <Card>
        <CardContent className="flex items-center gap-6 py-8">
          {statusIcons[application.status] || statusIcons.pending}
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h2 className="text-xl font-bold capitalize">{application.purpose} Loan</h2>
              {(() => { const s = getDisplayStatus(application.status, application.decision); return (
                <Badge className={s.color} variant="outline">{s.label}</Badge>
              ) })()}
            </div>
            <p className="text-muted-foreground">
              {statusMessages[application.status] || 'Status unknown.'}
            </p>
            {(application.status === 'pending' || application.status === 'processing') && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground mt-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Your application is being assessed by our AI system...
              </div>
            )}
          </div>
        </CardContent>
      </Card>

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
