'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { XCircle, RefreshCw, TrendingUp } from 'lucide-react'
import Link from 'next/link'

interface DenialExplanationPanelProps {
  denialReasons: Array<{ code: string; reason: string; feature: string }>
  counterfactuals: Array<{ changes: Record<string, number>; statement: string }>
  reapplicationGuidance: {
    improvement_targets: Array<any>
    estimated_review_months: number
    message: string
  } | null
  creditScore: number | null
}

function getEquifaxBand(score: number): string {
  if (score <= 459) return 'Below Average'
  if (score <= 660) return 'Average'
  if (score <= 734) return 'Good'
  if (score <= 852) return 'Very Good'
  return 'Excellent'
}

export function DenialExplanationPanel({
  denialReasons,
  counterfactuals,
  reapplicationGuidance,
  creditScore,
}: DenialExplanationPanelProps) {
  if (!denialReasons || denialReasons.length === 0) return null

  return (
    <div className="space-y-4">
      {/* Card 1 — Why we couldn't approve */}
      <Card role="region" aria-label="Denial reasons">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <XCircle className="h-5 w-5 text-red-500" />
            Why we couldn&apos;t approve your application
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ul className="space-y-3">
            {denialReasons.map((r) => (
              <li key={r.code} className="flex items-start gap-3">
                <span className="shrink-0 font-mono text-xs text-muted-foreground mt-0.5">
                  {r.code}
                </span>
                <span className="text-sm">{r.reason}</span>
              </li>
            ))}
          </ul>

          {creditScore !== null && (
            <div className="rounded-lg border p-3 text-sm">
              <span className="text-muted-foreground">Credit score: </span>
              <span className="font-semibold">{creditScore}</span>
              <span className="text-muted-foreground"> — </span>
              <span className="font-medium">{getEquifaxBand(creditScore)}</span>
              <span className="text-muted-foreground"> (Equifax AU band)</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Card 2 — Try this and reapply (only if counterfactuals exist) */}
      {counterfactuals.length > 0 && (
        <Card role="region" aria-label="Counterfactual suggestions">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <RefreshCw className="h-5 w-5 text-blue-500" />
              Try this and reapply
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <ul className="list-disc list-inside space-y-2">
              {counterfactuals.map((cf, i) => (
                <li key={i} className="text-sm">
                  {cf.statement}
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground italic">
              This is not a guarantee of approval. All applications are assessed individually.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Card 3 — Improving your profile */}
      <Card role="region" aria-label="Profile improvement tips">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-green-500" />
            Improving your profile for the future
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ul className="list-disc list-inside space-y-2 text-sm">
            {/* Source: Pepper Money — https://www.peppermoney.com.au */}
            <li>Pay down existing debts before reapplying</li>
            {/* Source: Pepper Money — https://www.peppermoney.com.au */}
            <li>Reduce credit card limits you don&apos;t actively use</li>
            {/* Source: Unloan — https://www.unloan.com.au */}
            <li>Wait at least 6 months for your credit file to reflect improvements</li>
            {/* Source: Equifax AU — https://www.equifax.com.au */}
            <li>Check your credit report for errors and lodge disputes if needed</li>
          </ul>

          <div className="flex flex-col gap-2 pt-2">
            <Button asChild variant="outline">
              <Link href="/rights">Talk to a specialist</Link>
            </Button>
            <p className="text-xs text-muted-foreground">
              If you believe this decision is incorrect, you can lodge a complaint with the{' '}
              <Link href="/rights" className="underline hover:text-foreground">
                Australian Financial Complaints Authority (AFCA)
              </Link>
              .
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
