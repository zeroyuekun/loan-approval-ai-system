'use client'

import { useState } from 'react'
import { useModelMetrics, useTrainModel } from '@/hooks/useMetrics'
import { useDriftReports } from '@/hooks/useDriftReports'
import { useAuth } from '@/lib/auth'
import { ALGORITHM_LABELS } from '@/lib/utils'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Cpu, Loader2, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { ModelHeader, ElapsedTimer, TrainingBlockedNotice } from '@/components/metrics/ModelHeader'
import { TrainControl } from '@/components/metrics/TrainControl'
import { KpiStrip } from '@/components/metrics/KpiStrip'
import { PerformanceTab } from '@/components/metrics/tabs/PerformanceTab'
import { FairnessTab } from '@/components/metrics/tabs/FairnessTab'
import { CalibrationThresholdsTab } from '@/components/metrics/tabs/CalibrationThresholdsTab'
import { DriftTab } from '@/components/metrics/tabs/DriftTab'
import { DiagnosticsTab } from '@/components/metrics/tabs/DiagnosticsTab'
import { TryItTab } from '@/components/metrics/tabs/TryItTab'
import { ModelSummary } from '@/components/metrics/ModelSummary'

function TechnicalSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  )
}

export default function ModelMetricsPage() {
  const { data: metrics, isLoading, isError } = useModelMetrics()
  const { user } = useAuth()
  // Drift is only shown in the admin-only Technical details tab.
  const { data: driftReports } = useDriftReports(6, { enabled: user?.role === 'admin' })
  const { trainingStatus, trainingAlgorithm, blockedGates, errorMessage: trainErrorMessage, ...trainModel } = useTrainModel()
  const [selectedAlgorithm, setSelectedAlgorithm] = useState('xgb')
  const isTraining = trainModel.isPending || trainingStatus === 'training'
  const isAdmin = user?.role === 'admin'
  const canScore = user?.role === 'admin' || user?.role === 'officer'
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
          {trainingStatus === 'blocked' && !isTraining && <TrainingBlockedNotice gates={blockedGates} />}
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
        blockedGates={blockedGates}
        trainErrorMessage={trainErrorMessage}
      />

      <ModelSummary metrics={metrics} />

      <Tabs defaultValue="fairness">
        <TabsList className="flex-wrap">
          <TabsTrigger value="fairness">Fairness by group</TabsTrigger>
          {canScore && <TabsTrigger value="try-it">Try it</TabsTrigger>}
          {isAdmin && <TabsTrigger value="technical">Technical details</TabsTrigger>}
        </TabsList>

        <TabsContent value="fairness"><FairnessTab metrics={metrics} /></TabsContent>
        {canScore && <TabsContent value="try-it"><TryItTab /></TabsContent>}
        {isAdmin && (
          <TabsContent value="technical" className="space-y-10">
            <p className="text-sm text-muted-foreground">
              Data-science measures for model validation. The cards above summarise them in plain English.
            </p>
            <TechnicalSection title="Headline scores"><KpiStrip metrics={metrics} /></TechnicalSection>
            <TechnicalSection title="Errors and ranking"><PerformanceTab metrics={metrics} /></TechnicalSection>
            <TechnicalSection title="Calibration and thresholds"><CalibrationThresholdsTab metrics={metrics} /></TechnicalSection>
            {hasDrift && <TechnicalSection title="Drift"><DriftTab reports={driftReports} /></TechnicalSection>}
            <TechnicalSection title="Diagnostics"><DiagnosticsTab metrics={metrics} /></TechnicalSection>
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
