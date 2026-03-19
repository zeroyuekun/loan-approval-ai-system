'use client'

import { useState, useEffect } from 'react'
import { useModelMetrics, useTrainModel } from '@/hooks/useMetrics'
import { useAuth } from '@/lib/auth'
import { ConfusionMatrix } from '@/components/metrics/ConfusionMatrix'
import { ROCCurve } from '@/components/metrics/ROCCurve'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import { CalibrationChart } from '@/components/metrics/CalibrationChart'
import { ThresholdChart } from '@/components/metrics/ThresholdChart'
import { FairnessCard } from '@/components/metrics/FairnessCard'
import { DecileChart } from '@/components/metrics/DecileChart'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectItem } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { formatPercent } from '@/lib/utils'
import { Cpu, Loader2, CheckCircle, XCircle } from 'lucide-react'

function ElapsedTimer() {
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    const interval = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return <span>{mins > 0 ? `${mins}m ${secs}s` : `${secs}s`}</span>
}

export default function ModelMetricsPage() {
  const { data: metrics, isLoading, isError } = useModelMetrics()
  const { user } = useAuth()
  const { trainingStatus, trainingAlgorithm, ...trainModel } = useTrainModel()
  const [selectedAlgorithm, setSelectedAlgorithm] = useState('rf')
  const isTraining = trainModel.isPending || trainingStatus === 'training'
  const activeTrainingLabel = (trainingAlgorithm || selectedAlgorithm) === 'rf' ? 'Random Forest' : 'XGBoost'

  const handleTrain = () => {
    trainModel.mutate(selectedAlgorithm)
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="grid gap-6 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <XCircle className="h-12 w-12 mx-auto text-red-400" />
          <p className="text-muted-foreground">Failed to load model metrics</p>
          <p className="text-sm text-muted-foreground">Check that the backend is running and try refreshing the page.</p>
        </div>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-4">
          <Cpu className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No active model found</p>
          {user?.role === 'admin' && (
            <div className="flex items-center gap-2 justify-center">
              <Select value={selectedAlgorithm} onChange={(e) => setSelectedAlgorithm(e.target.value)}>
                <SelectItem value="rf">Random Forest</SelectItem>
                <SelectItem value="xgb">XGBoost</SelectItem>
              </Select>
              <Button onClick={handleTrain} disabled={isTraining}>
                {isTraining ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                {isTraining ? 'Training...' : 'Train Model'}
              </Button>
            </div>
          )}

          {/* Training overlay for no-model state */}
          {isTraining && (
            <Card className="mt-4 border-blue-200 bg-blue-50/50">
              <CardContent className="flex items-center gap-4 py-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-100">
                  <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                </div>
                <div className="text-left">
                  <p className="font-medium text-blue-900">Training {activeTrainingLabel} model...</p>
                  <p className="text-sm text-blue-600">
                    Running GridSearchCV with cross-validation. Elapsed: <ElapsedTimer />
                  </p>
                  <p className="text-xs text-blue-500 mt-1">Typically 3-5 minutes. You can navigate away — training continues in the background.</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    )
  }

  const algorithmLabel = metrics.algorithm === 'rf' ? 'Random Forest' : 'XGBoost'

  return (
    <div className="space-y-6">
      {/* Model Info + Train */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">{algorithmLabel}</h3>
          <Badge variant="secondary" className="text-sm px-3 py-0.5">v{metrics.version}</Badge>
          {metrics.is_active && <Badge variant="success" className="text-sm px-3 py-0.5">Active</Badge>}
        </div>
        {user?.role === 'admin' && (
          <div className="flex items-center gap-2">
            <Select value={selectedAlgorithm} onChange={(e) => setSelectedAlgorithm(e.target.value)}>
              <SelectItem value="rf">Random Forest</SelectItem>
              <SelectItem value="xgb">XGBoost</SelectItem>
            </Select>
            <Button onClick={handleTrain} disabled={isTraining}>
              {isTraining ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {isTraining ? 'Training...' : 'Train New Model'}
            </Button>
          </div>
        )}
      </div>

      {/* Training progress banner */}
      {isTraining && (
        <Card className="border-blue-200 bg-gradient-to-r from-blue-50 to-indigo-50">
          <CardContent className="flex items-center gap-4 py-5">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-100 shrink-0">
              <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-blue-900">
                Training {activeTrainingLabel} model...
              </p>
              <p className="text-sm text-blue-700 mt-0.5">
                Running GridSearchCV with 3-fold cross-validation on 10,000 samples
              </p>
              <div className="flex items-center gap-4 mt-2">
                <span className="text-xs font-medium text-blue-600 bg-blue-100 px-2 py-0.5 rounded-full">
                  Elapsed: <ElapsedTimer />
                </span>
                <span className="text-xs text-blue-500">Typically 3-5 minutes</span>
              </div>
            </div>
            <div className="hidden sm:block">
              <div className="h-2 w-32 rounded-full bg-blue-100 overflow-hidden">
                <div className="h-full w-full bg-blue-500 rounded-full animate-pulse origin-left" style={{ animation: 'pulse 2s ease-in-out infinite' }} />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Success banner */}
      {trainingStatus === 'success' && !isTraining && (
        <Card className="border-emerald-200 bg-gradient-to-r from-emerald-50 to-green-50">
          <CardContent className="flex items-center gap-3 py-4">
            <CheckCircle className="h-5 w-5 text-emerald-600 shrink-0" />
            <p className="text-sm font-medium text-emerald-800">Model training complete. Metrics have been updated.</p>
          </CardContent>
        </Card>
      )}

      {/* Error banner */}
      {(trainModel.isError || trainingStatus === 'failure') && !isTraining && (
        <Card className="border-red-200 bg-gradient-to-r from-red-50 to-rose-50">
          <CardContent className="flex items-center gap-3 py-4">
            <XCircle className="h-5 w-5 text-red-600 shrink-0" />
            <p className="text-sm font-medium text-red-800">Model training failed. Please try again.</p>
          </CardContent>
        </Card>
      )}

      {/* Key Metrics */}
      <div className="grid gap-4 md:grid-cols-4">
        {[
          { label: 'Accuracy', value: metrics.accuracy },
          { label: 'Precision', value: metrics.precision },
          { label: 'Recall', value: metrics.recall },
          { label: 'F1 Score', value: metrics.f1_score },
          { label: 'AUC-ROC', value: metrics.auc_roc },
          ...(metrics.gini_coefficient != null ? [{ label: 'Gini Coefficient', value: metrics.gini_coefficient }] : []),
          ...(metrics.ks_statistic != null ? [{ label: 'KS Statistic', value: metrics.ks_statistic }] : []),
          ...(metrics.brier_score != null ? [{ label: 'Brier Score', value: metrics.brier_score }] : []),
        ].map((m) => (
          <Card key={m.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground">{m.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">
                {m.value != null
                  ? ['Brier Score', 'Gini Coefficient', 'KS Statistic'].includes(m.label)
                    ? m.value.toFixed(4)
                    : formatPercent(m.value)
                  : '—'}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Charts */}
      <div className="grid gap-6 md:grid-cols-2">
        {metrics.confusion_matrix && Object.keys(metrics.confusion_matrix).length > 0 && (
          <ConfusionMatrix matrix={metrics.confusion_matrix} />
        )}
        {metrics.roc_curve_data?.fpr && metrics.roc_curve_data?.tpr && (
          <ROCCurve
            fpr={metrics.roc_curve_data.fpr}
            tpr={metrics.roc_curve_data.tpr}
            auc={metrics.auc_roc ?? 0}
          />
        )}
      </div>

      {metrics.feature_importances && (Array.isArray(metrics.feature_importances) ? metrics.feature_importances.length > 0 : Object.keys(metrics.feature_importances).length > 0) && (
        <FeatureImportance features={metrics.feature_importances} />
      )}

      {/* Banking Metrics */}
      {(metrics.calibration_data?.fraction_of_positives || metrics.threshold_analysis?.sweep) && (
        <>
          <h3 className="text-lg font-semibold mt-8">Banking Metrics</h3>
          <div className="grid gap-6 md:grid-cols-2">
            {metrics.calibration_data?.fraction_of_positives && (
              <CalibrationChart
                fractionOfPositives={metrics.calibration_data.fraction_of_positives}
                meanPredictedValue={metrics.calibration_data.mean_predicted_value}
                ece={metrics.calibration_data.ece}
              />
            )}
            {metrics.threshold_analysis?.sweep && (
              <ThresholdChart
                sweep={metrics.threshold_analysis.sweep}
                f1OptimalThreshold={metrics.threshold_analysis.f1_optimal_threshold}
                youdenJThreshold={metrics.threshold_analysis.youden_j_threshold}
                costOptimalThreshold={metrics.threshold_analysis.cost_optimal_threshold}
              />
            )}
          </div>
        </>
      )}

      {/* Fairness Analysis */}
      {metrics.fairness_metrics && Object.keys(metrics.fairness_metrics).length > 0 && (
        <>
          <h3 className="text-lg font-semibold mt-8">Fairness Analysis</h3>
          <FairnessCard fairnessMetrics={metrics.fairness_metrics} />
        </>
      )}

      {/* Model Diagnostics */}
      {(metrics.decile_analysis?.deciles || metrics.training_metadata) && (
        <>
          <h3 className="text-lg font-semibold mt-8">Model Diagnostics</h3>
          <div className="grid gap-6 md:grid-cols-2">
            {metrics.decile_analysis?.deciles && (
              <DecileChart deciles={metrics.decile_analysis.deciles} />
            )}
            {metrics.training_metadata && Object.keys(metrics.training_metadata).length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Training Metadata</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {Object.entries(metrics.training_metadata).map(([key, value]) => (
                    <div key={key} className="flex justify-between">
                      <span className="text-muted-foreground">{key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>
                      <span className="font-mono">
                        {typeof value === 'number' ? (Number.isInteger(value) ? value : value.toFixed(4)) : String(value)}
                      </span>
                    </div>
                  ))}
                  {metrics.optimal_threshold != null && (
                    <div className="flex justify-between pt-2 border-t">
                      <span className="text-muted-foreground font-medium">Active Threshold</span>
                      <span className="font-mono font-semibold">{metrics.optimal_threshold.toFixed(2)}</span>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  )
}
