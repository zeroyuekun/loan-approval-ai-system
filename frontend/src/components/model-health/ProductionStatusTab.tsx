'use client'

import type { ModelMetrics, DriftReport } from '@/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DriftOverview } from '@/components/metrics/DriftOverview'
import { DriftPsiChart } from '@/components/metrics/DriftPsiChart'
import { FairnessCard } from '@/components/metrics/FairnessCard'
import { CalibrationChart } from '@/components/metrics/CalibrationChart'
import { ThresholdChart } from '@/components/metrics/ThresholdChart'
import { AlertTriangle } from 'lucide-react'

interface ProductionStatusTabProps {
  metrics: ModelMetrics
  driftReports: DriftReport[]
}

function getAlerts(metrics: ModelMetrics, driftReports: DriftReport[]): string[] {
  const out: string[] = []
  const latest = driftReports[0]
  if (latest && latest.alert_level === 'significant') {
    out.push(`Drift: PSI ${latest.psi_score?.toFixed(2) ?? 'n/a'} — significant breach`)
  }
  const fm = metrics.fairness_metrics || {}
  const failing = Object.entries(fm)
    .filter(([, v]: [string, any]) => v && v.passes_80_percent_rule === false)
    .map(([k]) => k)
  if (failing.length > 0) {
    out.push(`Fairness: failing on ${failing.join(', ')}`)
  }
  const ece = metrics.calibration_data?.ece
  if (typeof ece === 'number' && ece > 0.10) {
    out.push(`Calibration: ECE ${ece.toFixed(3)} (>0.10 is poor)`)
  }
  return out
}

export function ProductionStatusTab({ metrics, driftReports }: ProductionStatusTabProps) {
  const alerts = getAlerts(metrics, driftReports)
  return (
    <div className="space-y-6 mt-4">
      {alerts.length > 0 && (
        <div role="region" aria-label="Alerts" className="rounded-lg border border-rose-200 bg-rose-50/60 p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-rose-600 shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-rose-800">Alerts requiring attention</p>
              <ul className="mt-2 space-y-1">
                {alerts.map((a) => (
                  <li key={a} className="text-sm text-rose-700">{a}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Drift */}
      {driftReports.length > 0 ? (
        <div className="grid gap-6 md:grid-cols-2">
          <DriftOverview reports={driftReports} />
          <DriftPsiChart reports={driftReports} />
        </div>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Drift</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">No drift reports yet.</p>
          </CardContent>
        </Card>
      )}

      {/* Fairness */}
      {metrics.fairness_metrics && Object.keys(metrics.fairness_metrics).length > 0 ? (
        <FairnessCard fairnessMetrics={metrics.fairness_metrics} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Fairness</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">No fairness metrics recorded for the active model.</p>
          </CardContent>
        </Card>
      )}

      {/* Calibration + Threshold side-by-side */}
      <div className="grid gap-6 md:grid-cols-2">
        {metrics.calibration_data?.fraction_of_positives && metrics.calibration_data.fraction_of_positives.length > 0 ? (
          <CalibrationChart
            fractionOfPositives={metrics.calibration_data.fraction_of_positives}
            meanPredictedValue={metrics.calibration_data.mean_predicted_value}
            ece={metrics.calibration_data.ece}
          />
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Calibration</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">No calibration data available.</p>
            </CardContent>
          </Card>
        )}
        {metrics.threshold_analysis?.sweep && metrics.threshold_analysis.sweep.length > 0 ? (
          <ThresholdChart
            sweep={metrics.threshold_analysis.sweep}
            f1OptimalThreshold={metrics.threshold_analysis.f1_optimal_threshold}
            youdenJThreshold={metrics.threshold_analysis.youden_j_threshold}
            costOptimalThreshold={metrics.threshold_analysis.cost_optimal_threshold}
          />
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Threshold</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">No threshold analysis available.</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
