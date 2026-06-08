'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DecileChart } from '@/components/metrics/DecileChart'
import { curateMetadata, formatMetadataValue } from '@/components/metrics/diagnostics'
import { ModelMetrics } from '@/types'

export function DiagnosticsTab({ metrics }: { metrics: ModelMetrics }) {
  const metadataRows = curateMetadata(metrics.training_metadata)
  const scalars = [
    { label: 'Gini', value: metrics.gini_coefficient },
    { label: 'KS Statistic', value: metrics.ks_statistic },
    { label: 'Brier Score', value: metrics.brier_score },
    { label: 'Log Loss', value: metrics.log_loss },
    { label: 'ECE', value: metrics.ece },
    { label: 'Active Threshold', value: metrics.optimal_threshold },
  ].filter((s) => s.value != null)

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        {scalars.length > 0 && (
          <Card>
            <CardHeader className="pb-4"><CardTitle className="text-base">Advanced Scalars</CardTitle></CardHeader>
            <CardContent className="px-0">
              <div className="divide-y divide-border">
                {scalars.map((s) => (
                  <div key={s.label} className="grid grid-cols-2 gap-4 px-6 py-2.5">
                    <span className="text-sm text-muted-foreground">{s.label}</span>
                    <span className="text-right font-mono text-sm tabular-nums">{(s.value as number).toFixed(4)}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
        {metadataRows.length > 0 && (
          <Card>
            <CardHeader className="pb-4"><CardTitle className="text-base">Training Metadata</CardTitle></CardHeader>
            <CardContent className="px-0">
              <div className="divide-y divide-border">
                {metadataRows.map((row) => (
                  <div key={row.key} className="grid grid-cols-2 gap-4 px-6 py-2.5">
                    <span className="text-sm text-muted-foreground">{row.label}</span>
                    <span className="truncate text-right font-mono text-sm tabular-nums" title={formatMetadataValue(row.value)}>
                      {formatMetadataValue(row.value)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
      {metrics.decile_analysis?.deciles && <DecileChart deciles={metrics.decile_analysis.deciles} />}
    </div>
  )
}
