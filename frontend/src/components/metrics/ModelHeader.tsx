'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Loader2, CheckCircle, XCircle, AlertTriangle } from 'lucide-react'
import { TrainControl } from './TrainControl'
import { ModelMetrics } from '@/types'
import { ALGORITHM_LABELS } from '@/lib/utils'
import type { TrainingStatus } from '@/hooks/useMetrics'

// Pre-activation gates the training task can report in `activation_blocked`.
const GATE_LABELS: Record<string, string> = {
  fairness: 'fairness',
  promotion: 'promotion (champion-challenger and overfitting checks)',
  validation: 'validation sign-off',
}

/** Warning shown when a training run finished but a gate kept the new model inactive. */
export function TrainingBlockedNotice({ gates }: { gates: string[] }) {
  const named = gates.map((g) => GATE_LABELS[g] || g).join(', ')
  return (
    <Card className="border-amber-200 bg-gradient-to-r from-amber-50 to-yellow-50">
      <CardContent className="flex items-center gap-3 py-4">
        <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" />
        <p role="status" className="text-sm font-medium text-amber-800">
          The new model was trained but not activated{named ? `: blocked by the ${named} gate${gates.length > 1 ? 's' : ''}` : ''}. The current model keeps serving.
        </p>
      </CardContent>
    </Card>
  )
}

export function ElapsedTimer() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(interval)
  }, [])
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return <span>{mins > 0 ? `${mins}m ${secs}s` : `${secs}s`}</span>
}

interface ModelHeaderProps {
  metrics: ModelMetrics
  isAdmin: boolean
  selectedAlgorithm: string
  onSelect: (value: string) => void
  onTrain: () => void
  isTraining: boolean
  activeTrainingLabel: string
  trainingStatus: TrainingStatus
  blockedGates?: string[]
  trainErrorMessage: string | null
}

export function ModelHeader(props: ModelHeaderProps) {
  const { metrics, isAdmin, selectedAlgorithm, onSelect, onTrain, isTraining, activeTrainingLabel, trainingStatus, blockedGates = [], trainErrorMessage } = props
  const algorithmLabel = ALGORITHM_LABELS[metrics.algorithm] || metrics.algorithm

  return (
    <>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">{algorithmLabel}</h3>
          <Badge variant="secondary" className="px-3 py-0.5 text-sm">v{metrics.version}</Badge>
          {metrics.is_active && <Badge variant="success" className="px-3 py-0.5 text-sm">Active</Badge>}
        </div>
        {isAdmin && (
          <TrainControl selectedAlgorithm={selectedAlgorithm} onSelect={onSelect} onTrain={onTrain} isTraining={isTraining} label="Train New Model" />
        )}
      </div>

      {isTraining && (
        <Card className="border-blue-200 bg-gradient-to-r from-blue-50 to-indigo-50">
          <CardContent className="flex items-center gap-4 py-5">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-100">
              <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-blue-900">Training {activeTrainingLabel} model...</p>
              <p className="mt-0.5 text-sm text-blue-700">Running Optuna Bayesian optimization with 3-fold cross-validation</p>
              <div className="mt-2 flex items-center gap-4">
                <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-600">Elapsed: <ElapsedTimer /></span>
                <span className="text-xs text-blue-500">Typically 3-5 minutes</span>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {trainingStatus === 'success' && !isTraining && (
        <Card className="border-emerald-200 bg-gradient-to-r from-emerald-50 to-green-50">
          <CardContent className="flex items-center gap-3 py-4">
            <CheckCircle className="h-5 w-5 shrink-0 text-emerald-600" />
            <p className="text-sm font-medium text-emerald-800">Model training complete. Metrics have been updated.</p>
          </CardContent>
        </Card>
      )}

      {trainingStatus === 'blocked' && !isTraining && <TrainingBlockedNotice gates={blockedGates} />}

      {trainingStatus === 'skipped' && !isTraining && (
        <Card className="border-amber-200 bg-gradient-to-r from-amber-50 to-yellow-50">
          <CardContent className="flex items-center gap-3 py-4">
            <XCircle className="h-5 w-5 shrink-0 text-amber-600" />
            <p className="text-sm font-medium text-amber-800">Training was skipped because another training job was already in progress. The active model was not retrained.</p>
          </CardContent>
        </Card>
      )}

      {(trainErrorMessage || trainingStatus === 'failure') && !isTraining && (
        <Card className="border-red-200 bg-gradient-to-r from-red-50 to-rose-50">
          <CardContent className="flex items-center gap-3 py-4">
            <XCircle className="h-5 w-5 shrink-0 text-red-600" />
            <p className="text-sm font-medium text-red-800">{trainErrorMessage || 'Model training failed. Please try again.'}</p>
          </CardContent>
        </Card>
      )}
    </>
  )
}
