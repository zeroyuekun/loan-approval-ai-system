'use client'

import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { LoanApplication } from '@/types'
import { formatDate, formatPercent, formatPurpose, getDisplayStatus } from '@/lib/utils'

interface ApplicationHeaderProps {
  application: LoanApplication
}

export function ApplicationHeader({ application }: ApplicationHeaderProps) {
  return (
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
          {(() => { const s = getDisplayStatus(application.status, application.decision); return (
            <Badge className={s.color} variant="outline">{s.label}</Badge>
          ) })()}
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Created</span>
          <span>{formatDate(application.created_at)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Purpose</span>
          <span>{formatPurpose(application.purpose)}</span>
        </div>

        {/* ML decision summary — folded in here rather than a standalone box */}
        {application.decision && (
          <div className="space-y-3 border-t pt-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Model Confidence</span>
              <span>{formatPercent(application.decision.confidence)}</span>
            </div>
            {application.decision.risk_score != null && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Risk Score</span>
                <span>{Number(application.decision.risk_score).toFixed(2)}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-muted-foreground">Model</span>
              <span className="font-mono text-sm">{application.decision.model_version}</span>
            </div>
            {application.decision.reasoning && (
              <div>
                <span className="text-muted-foreground">Model Reasoning</span>
                <p className="mt-1 text-sm">{application.decision.reasoning}</p>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
