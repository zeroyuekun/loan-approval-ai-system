'use client'

import { CalibrationChart } from '@/components/metrics/CalibrationChart'
import { ThresholdChart } from '@/components/metrics/ThresholdChart'
import { ModelMetrics } from '@/types'

export function CalibrationThresholdsTab({ metrics }: { metrics: ModelMetrics }) {
  const hasCalibration = metrics.calibration_data?.fraction_of_positives
  const hasThreshold = metrics.threshold_analysis?.sweep

  if (!hasCalibration && !hasThreshold) {
    return <p className="text-sm text-muted-foreground">No calibration or threshold data available for this model.</p>
  }

  return (
    <div className="grid gap-6 md:grid-cols-2">
      {hasCalibration && (
        <CalibrationChart
          fractionOfPositives={metrics.calibration_data!.fraction_of_positives}
          meanPredictedValue={metrics.calibration_data!.mean_predicted_value}
          ece={metrics.calibration_data!.ece}
        />
      )}
      {hasThreshold && (
        <ThresholdChart
          sweep={metrics.threshold_analysis!.sweep}
          f1OptimalThreshold={metrics.threshold_analysis!.f1_optimal_threshold}
          youdenJThreshold={metrics.threshold_analysis!.youden_j_threshold}
          costOptimalThreshold={metrics.threshold_analysis!.cost_optimal_threshold}
        />
      )}
    </div>
  )
}
