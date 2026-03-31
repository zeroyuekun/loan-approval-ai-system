'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoanDecision } from '@/types'
import { formatPercent } from '@/lib/utils'
import { loansApi } from '@/lib/api'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import { ShapWaterfall } from '@/components/metrics/ShapWaterfall'
import { Download, Loader2 } from 'lucide-react'

interface DecisionSectionProps {
  decision: LoanDecision
  loanId: string
}

export function DecisionSection({ decision, loanId }: DecisionSectionProps) {
  const [downloading, setDownloading] = useState(false)

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const response = await loansApi.downloadDecisionLetter(loanId)
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `decision-letter-${loanId}.pdf`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Failed to download decision letter:', error)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">ML Decision</CardTitle>
            <CardDescription>Model: {decision.model_version}</CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDownload}
            disabled={downloading}
          >
            {downloading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-2 h-4 w-4" />
            )}
            {downloading ? 'Generating...' : 'Download Decision Letter'}
          </Button>
        </div>
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
        {decision.shap_values && Object.keys(decision.shap_values).length > 0 && (
          <ShapWaterfall shapValues={decision.shap_values} />
        )}
      </CardContent>
    </Card>
  )
}
