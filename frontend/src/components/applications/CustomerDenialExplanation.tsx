'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'
import type { LoanDecision } from '@/types'
import { FileText, Phone, ArrowRight } from 'lucide-react'

interface Props {
  decision: LoanDecision
}

export function CustomerDenialExplanation({ decision }: Props) {
  if (decision.decision !== 'denied') return null

  const reasons = decision.denial_reasons ?? []
  const guidance = decision.reapplication_guidance

  return (
    <div className="space-y-4">
      {/* Denial Reasons */}
      {reasons.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Understanding your assessment outcome
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">
              The following factors had the greatest influence on this decision:
            </p>
            <ol className="space-y-3">
              {reasons.map((r, i) => (
                <li key={r.code} className="flex items-start gap-3">
                  <Badge variant="outline" className="shrink-0 font-mono text-xs mt-0.5">
                    {r.code}
                  </Badge>
                  <span className="text-sm">{r.reason}</span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}

      {/* Reapplication Guidance */}
      {guidance && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <ArrowRight className="h-4 w-4" />
              What you can do
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {guidance.improvement_targets.length > 0 && (
              <ul className="space-y-2">
                {guidance.improvement_targets.map((t, i) => (
                  <li key={i} className="text-sm">
                    <span className="font-medium">{t.description || t.feature}</span>
                    {t.current_value && t.target_value && (
                      <span className="text-muted-foreground">
                        {' '}(current: {t.current_value} &rarr; target: {t.target_value})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="text-sm text-muted-foreground">{guidance.message}</p>
          </CardContent>
        </Card>
      )}

      {/* Rights */}
      <Card className="border-blue-200 bg-blue-50/50 dark:border-blue-900 dark:bg-blue-950/20">
        <CardContent className="pt-6">
          <div className="flex items-start gap-3">
            <Phone className="h-4 w-4 mt-0.5 text-blue-600 dark:text-blue-400 shrink-0" />
            <div className="text-sm space-y-1">
              <p className="font-medium">Your rights</p>
              <p className="text-muted-foreground">
                You have the right to request a free copy of the credit information used in this assessment.
                If you believe this decision is incorrect, you can lodge a complaint with the{' '}
                <strong>Australian Financial Complaints Authority (AFCA)</strong> on{' '}
                <strong>1800 931 678</strong>.
              </p>
              <Link
                href="/rights"
                className="text-blue-600 dark:text-blue-400 hover:underline inline-block mt-1"
              >
                View your full rights &rarr;
              </Link>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
