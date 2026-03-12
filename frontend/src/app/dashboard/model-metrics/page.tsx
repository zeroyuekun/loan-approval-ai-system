'use client'

import { useState } from 'react'
import { useModelMetrics, useTrainModel } from '@/hooks/useMetrics'
import { useAuth } from '@/lib/auth'
import { ConfusionMatrix } from '@/components/metrics/ConfusionMatrix'
import { ROCCurve } from '@/components/metrics/ROCCurve'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectItem } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { formatPercent } from '@/lib/utils'
import { Cpu, Loader2 } from 'lucide-react'

export default function ModelMetricsPage() {
  const { data: metrics, isLoading } = useModelMetrics()
  const { user } = useAuth()
  const trainModel = useTrainModel()
  const [selectedAlgorithm, setSelectedAlgorithm] = useState('rf')

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
              <Button onClick={handleTrain} disabled={trainModel.isPending}>
                {trainModel.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Train Model
              </Button>
            </div>
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
          <Badge variant="secondary">v{metrics.version}</Badge>
          {metrics.is_active && <Badge>Active</Badge>}
        </div>
        {user?.role === 'admin' && (
          <div className="flex items-center gap-2">
            <Select value={selectedAlgorithm} onChange={(e) => setSelectedAlgorithm(e.target.value)}>
              <SelectItem value="rf">Random Forest</SelectItem>
              <SelectItem value="xgb">XGBoost</SelectItem>
            </Select>
            <Button onClick={handleTrain} disabled={trainModel.isPending}>
              {trainModel.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Train New Model
            </Button>
          </div>
        )}
      </div>

      {/* Key Metrics */}
      <div className="grid gap-4 md:grid-cols-5">
        {[
          { label: 'Accuracy', value: metrics.accuracy },
          { label: 'Precision', value: metrics.precision },
          { label: 'Recall', value: metrics.recall },
          { label: 'F1 Score', value: metrics.f1_score },
          { label: 'AUC-ROC', value: metrics.auc_roc },
        ].map((m) => (
          <Card key={m.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground">{m.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{formatPercent(m.value)}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Charts */}
      <div className="grid gap-6 md:grid-cols-2">
        <ConfusionMatrix matrix={metrics.confusion_matrix} />
        {metrics.roc_curve_data && (
          <ROCCurve
            fpr={metrics.roc_curve_data.fpr}
            tpr={metrics.roc_curve_data.tpr}
            auc={metrics.auc_roc}
          />
        )}
      </div>

      {metrics.feature_importances && Object.keys(metrics.feature_importances).length > 0 && (
        <FeatureImportance features={metrics.feature_importances} />
      )}

      {trainModel.isError && (
        <div className="rounded-md bg-destructive/10 p-3">
          <p className="text-sm text-destructive">Failed to start model training. Please try again.</p>
        </div>
      )}

      {trainModel.isSuccess && (
        <div className="rounded-md bg-green-50 p-3">
          <p className="text-sm text-green-700">Model training started successfully. This may take a few minutes.</p>
        </div>
      )}
    </div>
  )
}
