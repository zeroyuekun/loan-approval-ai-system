'use client'

import { useState } from 'react'
import { useModelMetrics, useTrainModel } from '@/hooks/useMetrics'
import { useDriftReports } from '@/hooks/useDriftReports'
import { useAuth } from '@/lib/auth'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Cpu, Loader2, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { ModelHeader, ElapsedTimer } from '@/components/metrics/ModelHeader'
import { TrainControl } from '@/components/metrics/TrainControl'
import { KpiStrip } from '@/components/metrics/KpiStrip'
import { PerformanceTab } from '@/components/metrics/tabs/PerformanceTab'
import { FairnessTab } from '@/components/metrics/tabs/FairnessTab'
import { CalibrationThresholdsTab } from '@/components/metrics/tabs/CalibrationThresholdsTab'
import { DriftTab } from '@/components/metrics/tabs/DriftTab'
import { DiagnosticsTab } from '@/components/metrics/tabs/DiagnosticsTab'

const ALGORITHM_LABELS: Record<string, string> = { rf: 'Random Forest', xgb: 'XGBoost' }

export default function ModelMetricsPage() {
  const { data: metrics, isLoading, isError } = useModelMetrics()
  const { data: driftReports } = useDriftReports(6)
  const { user } = useAuth()
  const { trainingStatus, trainingAlgorithm, errorMessage: trainErrorMessage, ...trainModel } = useTrainModel()
  const [selectedAlgorithm, setSelectedAlgorithm] = useState('xgb')
  const isTraining = trainModel.isPending || trainingStatus === 'training'
  const isAdmin = user?.role === 'admin'
  const activeTrainingLabel = ALGORITHM_LABELS[trainingAlgorithm || selectedAlgorithm] || selectedAlgorithm

  const handleTrain = () => {
    trainModel.mutate(selectedAlgorithm, {
      onSuccess: () => toast.success('Model training started'),
      onError: (err: any) => {
        const status = err?.response?.status
        const detail = err?.response?.data?.detail || err?.response?.data?.error
        if (status === 429) toast.error(detail ? `Rate limit reached: ${detail}` : 'Training rate limit reached. Please wait a few minutes before retrying.')
        else if (status === 409) toast.error(detail || 'A training job is already in progress. Please wait for it to complete.')
        else if (status === 403) toast.error('You do not have permission to train models.')
        else if (status === 400) toast.error(detail || 'Invalid training request.')
        else toast.error('Failed to start training')
      },
    })
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="grid gap-6 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-64" />)}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="space-y-2 text-center">
          <XCircle className="mx-auto h-12 w-12 text-red-400" />
          <p className="text-muted-foreground">Failed to load model metrics</p>
          <p className="text-sm text-muted-foreground">Check that the backend is running and try refreshing the page.</p>
        </div>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="space-y-4 text-center">
          <Cpu className="mx-auto h-12 w-12 text-muted-foreground" />
          <p className="text-muted-foreground">No active model found</p>
          {isAdmin && (
            <div className="flex justify-center">
              <TrainControl selectedAlgorithm={selectedAlgorithm} onSelect={setSelectedAlgorithm} onTrain={handleTrain} isTraining={isTraining} label="Train Model" />
            </div>
          )}
          {isTraining && (
            <Card className="mt-4 border-blue-200 bg-blue-50/50">
              <CardContent className="flex items-center gap-4 py-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-100">
                  <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                </div>
                <div className="text-left">
                  <p className="font-medium text-blue-900">Training {activeTrainingLabel} model...</p>
                  <p className="text-sm text-blue-600">Running Optuna Bayesian optimization with cross-validation. Elapsed: <ElapsedTimer /></p>
                  <p className="mt-1 text-xs text-blue-500">Typically 3-5 minutes. You can navigate away — training continues in the background.</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    )
  }

  const hasDrift = !!driftReports && driftReports.length > 0

  return (
    <div className="space-y-6">
      <ModelHeader
        metrics={metrics}
        isAdmin={isAdmin}
        selectedAlgorithm={selectedAlgorithm}
        onSelect={setSelectedAlgorithm}
        onTrain={handleTrain}
        isTraining={isTraining}
        activeTrainingLabel={activeTrainingLabel}
        trainingStatus={trainingStatus}
        trainError={trainModel.isError}
        trainErrorMessage={trainErrorMessage}
      />

      <KpiStrip metrics={metrics} />

      <Tabs defaultValue="performance">
        <TabsList className="flex-wrap">
          <TabsTrigger value="performance">Performance</TabsTrigger>
          <TabsTrigger value="fairness">Fairness</TabsTrigger>
          <TabsTrigger value="calibration">Calibration &amp; Thresholds</TabsTrigger>
          {hasDrift && <TabsTrigger value="drift">Drift</TabsTrigger>}
          <TabsTrigger value="diagnostics">Diagnostics</TabsTrigger>
        </TabsList>

        <TabsContent value="performance"><PerformanceTab metrics={metrics} /></TabsContent>
        <TabsContent value="fairness"><FairnessTab metrics={metrics} /></TabsContent>
        <TabsContent value="calibration"><CalibrationThresholdsTab metrics={metrics} /></TabsContent>
        {hasDrift && <TabsContent value="drift"><DriftTab reports={driftReports} /></TabsContent>}
        <TabsContent value="diagnostics"><DiagnosticsTab metrics={metrics} /></TabsContent>
      </Tabs>
    </div>
  )
}
