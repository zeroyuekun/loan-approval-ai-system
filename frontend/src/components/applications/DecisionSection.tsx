'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { LoanDecision } from '@/types'
import { formatPercent } from '@/lib/utils'

interface DecisionSectionProps {
  decision: LoanDecision
}

export function DecisionSection({ decision }: DecisionSectionProps) {
  return (
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
      </CardContent>
    </Card>
  )
}
