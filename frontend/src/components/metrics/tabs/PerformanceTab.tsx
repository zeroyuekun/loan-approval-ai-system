'use client'

import { ConfusionMatrix } from '@/components/metrics/ConfusionMatrix'
import { ROCCurve } from '@/components/metrics/ROCCurve'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import { ModelMetrics } from '@/types'

export function PerformanceTab({ metrics }: { metrics: ModelMetrics }) {
  const hasConfusion = metrics.confusion_matrix && Object.keys(metrics.confusion_matrix).length > 0
  const hasRoc = metrics.roc_curve_data?.fpr && metrics.roc_curve_data?.tpr
  const features = metrics.feature_importances
  const hasFeatures = features && (Array.isArray(features) ? features.length > 0 : Object.keys(features).length > 0)

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        {hasConfusion && <ConfusionMatrix matrix={metrics.confusion_matrix} threshold={metrics.optimal_threshold} />}
        {hasRoc && <ROCCurve fpr={metrics.roc_curve_data.fpr!} tpr={metrics.roc_curve_data.tpr!} auc={metrics.auc_roc ?? 0} />}
      </div>
      {hasFeatures && <FeatureImportance features={features} />}
    </div>
  )
}
