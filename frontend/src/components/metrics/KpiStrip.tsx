'use client'

import { Card, CardContent } from '@/components/ui/card'
import { formatPercent } from '@/lib/utils'
import { ModelMetrics } from '@/types'

type KpiStripProps = {
  metrics: Pick<ModelMetrics, 'accuracy' | 'precision' | 'recall' | 'f1_score' | 'auc_roc'>
}

export function KpiStrip({ metrics }: KpiStripProps) {
  const secondary = [
    { label: 'Accuracy', value: metrics.accuracy },
    { label: 'Precision', value: metrics.precision },
    { label: 'Recall', value: metrics.recall },
    { label: 'F1 Score', value: metrics.f1_score },
  ]

  return (
    <div className="grid gap-4 grid-cols-2 lg:grid-cols-5">
      <Card className="col-span-2 border-primary/30 bg-primary/5 lg:col-span-1">
        <CardContent className="pt-5 pb-4">
          <p className="mb-1.5 text-xs font-medium text-primary/80">AUC-ROC</p>
          <p className="text-3xl font-bold tabular-nums text-primary">
            {metrics.auc_roc != null ? metrics.auc_roc.toFixed(3) : '—'}
          </p>
        </CardContent>
      </Card>
      {secondary.map((m) => (
        <Card key={m.label}>
          <CardContent className="pt-5 pb-4">
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">{m.label}</p>
            <p className="text-2xl font-bold tabular-nums">
              {m.value != null ? formatPercent(m.value) : '—'}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
