'use client'

import { FairnessCard } from '@/components/metrics/FairnessCard'
import { ModelMetrics } from '@/types'

export function FairnessTab({ metrics }: { metrics: ModelMetrics }) {
  if (!metrics.fairness_metrics || Object.keys(metrics.fairness_metrics).length === 0) {
    return <p className="text-sm text-muted-foreground">No fairness analysis available for this model.</p>
  }
  return <FairnessCard fairnessMetrics={metrics.fairness_metrics} />
}
