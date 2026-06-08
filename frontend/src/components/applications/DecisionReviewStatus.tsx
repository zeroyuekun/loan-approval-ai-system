'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Scale } from 'lucide-react'
import { useRequestDecisionReview, useDecisionReview } from '@/hooks/useDecisionReview'

const STATUS_LABEL: Record<string, string> = {
  requested: 'Requested — awaiting a lending officer',
  under_review: 'Under review by a lending officer',
  upheld: 'Reviewed — the original decision stands',
  overturned: 'Reviewed — decision overturned, your application was approved',
  withdrawn: 'Withdrawn',
}

export function DecisionReviewStatus({
  applicationId,
  allowRequest = true,
}: {
  applicationId: string
  /** Whether requesting a NEW review is valid here. The backend only accepts
   *  reviews on declined applications, so the approved/review screens pass false
   *  to avoid offering a form that 400s. Defaults true (the denial panel). */
  allowRequest?: boolean
}) {
  const { data: review } = useDecisionReview(applicationId)
  const requestReview = useRequestDecisionReview()
  const [reason, setReason] = useState('')

  if (review) {
    return (
      <Card role="region" aria-label="Human review status">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Scale className="h-5 w-5 text-blue-500" />
            Human review
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm">{STATUS_LABEL[review.status] ?? review.status}</p>
          {review.status === 'upheld' && (
            <p className="text-xs text-muted-foreground mt-2">
              If you remain dissatisfied you can lodge a formal complaint with AFCA — see{' '}
              <a href="/rights" className="underline">Your Rights</a>.
            </p>
          )}
        </CardContent>
      </Card>
    )
  }

  // No existing review: only offer the request form where contestation is valid
  // (the denied screen). On approved/review screens a new review is rejected by
  // the backend (must be 'denied'), so render nothing rather than a form that 400s.
  if (!allowRequest) {
    return null
  }

  return (
    <Card role="region" aria-label="Request a human review">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Scale className="h-5 w-5 text-blue-500" />
          Request a human review
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <textarea
          aria-label="Why do you think this decision is wrong?"
          placeholder="Tell us why you think this decision should be reviewed (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="w-full min-h-20 rounded-md border bg-background p-2 text-sm"
        />
        <Button
          onClick={() => requestReview.mutate({ application: applicationId, reason })}
          disabled={requestReview.isPending}
        >
          {requestReview.isPending ? 'Submitting…' : 'Request a human review'}
        </Button>
      </CardContent>
    </Card>
  )
}
