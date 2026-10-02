'use client'

import { formatPercent } from '@/lib/utils'
import { formatFeatureName } from '@/components/metrics/FeatureImportance'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AdhocScoreResult } from '@/types'

interface TryItResultProps {
  result: AdhocScoreResult
}

/** Renders one ad-hoc scoring response: probability, decision vs threshold,
 * top SHAP factors, which features fell back to training defaults, and the
 * honesty note the backend returns verbatim (see adhoc.py ADHOC_SCORE_NOTE). */
export function TryItResult({ result }: TryItResultProps) {
  const approved = result.decision === 'approved'

  return (
    <Card>
      <CardHeader>
        <CardTitle>Result</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <p className="text-sm text-muted-foreground">Probability of default</p>
            <p className="text-2xl font-semibold tabular-nums">{formatPercent(result.probability)}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Decision</p>
            <p className={`text-2xl font-semibold capitalize ${approved ? 'text-emerald-600' : 'text-destructive'}`}>
              {result.decision}
            </p>
            <p className="text-xs text-muted-foreground">against a threshold of {formatPercent(result.threshold)}</p>
          </div>
        </div>

        <div className="grid gap-4 text-sm md:grid-cols-2">
          <div>
            <span className="text-muted-foreground">Risk grade: </span>
            <span className="font-medium">{result.risk_grade}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Model version: </span>
            <span className="font-medium">{result.model_version}</span>
          </div>
        </div>

        {result.top_factors.length > 0 && (
          <div>
            <p className="mb-2 text-sm font-medium">Top factors</p>
            <ul className="space-y-1 text-sm">
              {result.top_factors.map((f) => (
                <li key={f.feature} className="flex justify-between gap-4">
                  <span>{formatFeatureName(f.feature)}</span>
                  <span className="font-mono tabular-nums">
                    {f.impact >= 0 ? '+' : ''}
                    {f.impact.toFixed(3)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {result.defaulted_features.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">
              {result.defaulted_features.length} model features used default values
            </summary>
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-muted-foreground">
              {result.defaulted_features.map((feature) => (
                <li key={feature}>{formatFeatureName(feature)}</li>
              ))}
            </ul>
          </details>
        )}

        <p className="border-t pt-3 text-xs text-muted-foreground">{result.note}</p>
      </CardContent>
    </Card>
  )
}
