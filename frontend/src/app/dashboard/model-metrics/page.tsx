'use client'

import { useState, useEffect } from 'react'
import { useModelMetrics, useTrainModel } from '@/hooks/useMetrics'
import { useDriftReports } from '@/hooks/useDriftReports'
import { useAuth } from '@/lib/auth'
import { CalibrationChart } from '@/components/metrics/CalibrationChart'
import { FairnessCard } from '@/components/metrics/FairnessCard'
import { DecileChart } from '@/components/metrics/DecileChart'
import { DriftOverview } from '@/components/metrics/DriftOverview'
import { DriftTrendChart } from '@/components/metrics/DriftTrendChart'
import { ModelCard } from '@/components/metrics/ModelCard'
import { KpiStrip } from '@/components/metrics/KpiStrip'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectItem } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Cpu, Loader2, CheckCircle, XCircle } from 'lucide-react'
import { toast } from 'sonner'

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
  const { data: driftReports } = useDriftReports(6)
  const { user } = useAuth()
  const { trainingStatus, trainingAlgorithm, errorMessage: trainErrorMessage, ...trainModel } = useTrainModel()
  const [selectedAlgorithm, setSelectedAlgorithm] = useState('xgb')
  const isTraining = trainModel.isPending || trainingStatus === 'training'
  const algorithmLabels: Record<string, string> = {
    rf: 'Random Forest', xgb: 'XGBoost',
  }
  const activeTrainingLabel = algorithmLabels[trainingAlgorithm || selectedAlgorithm] || selectedAlgorithm

  const handleTrain = () => {
    trainModel.mutate(selectedAlgorithm, {
      onSuccess: () => {
        toast.success('Model training started')
      },
      onError: (err: any) => {
        const status = err?.response?.status
        const detail = err?.response?.data?.detail || err?.response?.data?.error
        if (status === 429) {
          toast.error(detail ? `Rate limit reached: ${detail}` : 'Training rate limit reached. Please wait a few minutes before retrying.')
        } else if (status === 409) {
          toast.error(detail || 'A training job is already in progress. Please wait for it to complete.')
        } else if (status === 403) {
          toast.error('You do not have permission to train models.')
        } else if (status === 400) {
          toast.error(detail || 'Invalid training request.')
        } else {
          toast.error('Failed to start training')
        }
      },
    })
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
                <SelectItem value="xgb">XGBoost</SelectItem>
                <SelectItem value="rf">Random Forest</SelectItem>
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
                    Running Optuna Bayesian optimization with cross-validation. Elapsed: <ElapsedTimer />
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

  const algorithmLabel = algorithmLabels[metrics.algorithm] || metrics.algorithm
  const latestDrift = driftReports && driftReports.length > 0 ? driftReports[0] : null
  const previousDrift = driftReports && driftReports.length > 1 ? driftReports[1] : null

  return (
    <div className="space-y-6">
      {/* Header — algorithm + version + Active badge + Train control */}
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
                Running Optuna Bayesian optimization with 3-fold cross-validation
              </p>
              <div className="flex items-center gap-4 mt-2">
                <span className="text-xs font-medium text-blue-600 bg-blue-100 px-2 py-0.5 rounded-full">
                  Elapsed: <ElapsedTimer />
                </span>
                <span className="text-xs text-blue-500">Typically 3-5 minutes</span>
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

      {/* Skipped banner — task finished but no retraining happened */}
      {trainingStatus === 'skipped' && !isTraining && (
        <Card className="border-amber-200 bg-gradient-to-r from-amber-50 to-yellow-50">
          <CardContent className="flex items-center gap-3 py-4">
            <XCircle className="h-5 w-5 text-amber-600 shrink-0" />
            <p className="text-sm font-medium text-amber-800">
              Training was skipped because another training job was already in progress. The active model was not retrained.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Error banner */}
      {(trainModel.isError || trainingStatus === 'failure') && !isTraining && (
        <Card className="border-red-200 bg-gradient-to-r from-red-50 to-rose-50">
          <CardContent className="flex items-center gap-3 py-4">
            <XCircle className="h-5 w-5 text-red-600 shrink-0" />
            <p className="text-sm font-medium text-red-800">
              {trainErrorMessage || 'Model training failed. Please try again.'}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Lender-style KPI strip — first glance "is the model working today?" */}
      <KpiStrip metrics={metrics} latestDrift={latestDrift} previousDrift={previousDrift} />

      {/* ModelCard — performance + drivers + scope + posture, with raw
          training metadata behind a collapse. Absorbs every signal that
          legacy ConfusionMatrix / ROCCurve / ThresholdChart / ModelHealthCard
          used to render on this page. */}
      <ModelCard metrics={metrics} />

      {/* Calibration + Decile — the two visuals analysts actually use:
          "are the probabilities trustworthy" and "is risk concentrated
          where it should be". */}
      {(metrics.calibration_data?.fraction_of_positives || metrics.decile_analysis?.deciles) && (
        <div className="grid gap-6 md:grid-cols-2">
          {metrics.calibration_data?.fraction_of_positives && (
            <CalibrationChart
              fractionOfPositives={metrics.calibration_data.fraction_of_positives}
              meanPredictedValue={metrics.calibration_data.mean_predicted_value}
              ece={metrics.calibration_data.ece}
            />
          )}
          {metrics.decile_analysis?.deciles && (
            <DecileChart deciles={metrics.decile_analysis.deciles} />
          )}
        </div>
      )}

      {/* Stability summary + drift trend — population shifts and operational
          shifts on one row. */}
      {driftReports && driftReports.length > 0 && (
        <div className="grid gap-6 md:grid-cols-2">
          <DriftOverview reports={driftReports} />
          <DriftTrendChart reports={driftReports} />
        </div>
      )}

      {/* Fairness — one card per protected attribute, 4/5ths rule pass/fail */}
      {metrics.fairness_metrics && Object.keys(metrics.fairness_metrics).length > 0 && (
        <>
          <h3 className="text-lg font-semibold pt-2">Fairness Analysis</h3>
          <FairnessCard fairnessMetrics={metrics.fairness_metrics} />
        </>
      )}
    </div>
  )
}
