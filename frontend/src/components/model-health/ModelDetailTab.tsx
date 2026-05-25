'use client'

import { useState } from 'react'
import { useTrainModel } from '@/hooks/useMetrics'
import { useAuth } from '@/lib/auth'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectItem } from '@/components/ui/select'
import { ConfusionMatrix } from '@/components/metrics/ConfusionMatrix'
import { ROCCurve } from '@/components/metrics/ROCCurve'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import { DecileChart } from '@/components/metrics/DecileChart'
import { formatPercent } from '@/lib/utils'
import { Cpu, Loader2, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import type { ModelMetrics, ModelCard } from '@/types'

interface ModelDetailTabProps {
  metrics: ModelMetrics
  card: ModelCard | null | undefined
}

const ALGORITHM_LABELS: Record<string, string> = { rf: 'Random Forest', xgb: 'XGBoost' }

export function ModelDetailTab({ metrics, card: _card }: ModelDetailTabProps) {
  const { user } = useAuth()
  const { trainingStatus, ...trainModel } = useTrainModel()
  const [selectedAlgorithm, setSelectedAlgorithm] = useState('xgb')
  const isTraining = trainModel.isPending || trainingStatus === 'training'

  const handleTrain = () => {
    trainModel.mutate(selectedAlgorithm, {
      onSuccess: () => toast.success('Model training started'),
      onError: (err: any) => {
        const status = err?.response?.status
        const detail = err?.response?.data?.detail || err?.response?.data?.error
        if (status === 429) toast.error(detail ? `Rate limit reached: ${detail}` : 'Training rate limit reached.')
        else if (status === 409) toast.error(detail || 'A training job is already in progress.')
        else if (status === 403) toast.error('You do not have permission to train models.')
        else if (status === 400) toast.error(detail || 'Invalid training request.')
        else toast.error('Failed to start training')
      },
    })
  }

  const algorithmLabel = ALGORITHM_LABELS[metrics.algorithm] || metrics.algorithm
  const tiles = [
    { label: 'Accuracy', value: metrics.accuracy, fmt: 'pct' as const },
    { label: 'Precision', value: metrics.precision, fmt: 'pct' as const },
    { label: 'Recall', value: metrics.recall, fmt: 'pct' as const },
    { label: 'F1 Score', value: metrics.f1_score, fmt: 'pct' as const },
    { label: 'AUC-ROC', value: metrics.auc_roc, fmt: 'pct' as const },
    { label: 'Gini', value: metrics.gini_coefficient, fmt: 'num' as const },
    { label: 'KS Statistic', value: metrics.ks_statistic, fmt: 'num' as const },
    { label: 'Brier Score', value: metrics.brier_score, fmt: 'num' as const },
  ]

  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false)

  return (
    <div className="space-y-6 mt-4">
      {/* Header: summary + admin train control */}
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

      {/* Metric tiles */}
      <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
        {tiles.filter((m) => m.value != null).map((m) => (
          <Card key={m.label}>
            <CardContent className="pt-5 pb-4">
              <p className="text-xs font-medium text-muted-foreground mb-1.5">{m.label}</p>
              <p className="text-2xl font-bold tabular-nums">
                {m.fmt === 'pct' ? formatPercent(m.value!) : m.value!.toFixed(4)}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Feature importance + Decile */}
      {metrics.feature_importances && Object.keys(metrics.feature_importances).length > 0 && (
        <FeatureImportance features={metrics.feature_importances} />
      )}
      {metrics.decile_analysis?.deciles && metrics.decile_analysis.deciles.length > 0 && (
        <DecileChart deciles={metrics.decile_analysis.deciles} />
      )}

      {/* Diagnostics accordion: ROC + Confusion (collapsed by default) */}
      <Card>
        <button
          type="button"
          onClick={() => setDiagnosticsOpen((v) => !v)}
          aria-expanded={diagnosticsOpen}
          className="flex w-full items-center justify-between p-4 text-left"
        >
          <span className="flex items-center gap-2 text-base font-semibold">
            <Cpu className="h-4 w-4" />
            Diagnostics
            <span className="text-xs font-normal text-muted-foreground">(ROC curve + confusion matrix — rarely actionable once AUC is trusted)</span>
          </span>
          <ChevronDown className={`h-5 w-5 transition-transform ${diagnosticsOpen ? 'rotate-180' : ''}`} />
        </button>
        {diagnosticsOpen && (
          <CardContent className="pt-0 grid gap-6 md:grid-cols-2">
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
          </CardContent>
        )}
      </Card>
    </div>
  )
}
