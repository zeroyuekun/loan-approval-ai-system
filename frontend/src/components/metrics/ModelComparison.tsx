'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ModelMetrics } from '@/types'
import { formatPercent } from '@/lib/utils'

interface ModelComparisonProps {
  models: ModelMetrics[]
}

export function ModelComparison({ models }: ModelComparisonProps) {
  const metrics = ['accuracy', 'precision', 'recall', 'f1_score', 'auc_roc'] as const

  const metricLabels: Record<string, string> = {
    accuracy: 'Accuracy',
    precision: 'Precision',
    recall: 'Recall',
    f1_score: 'F1 Score',
    auc_roc: 'AUC-ROC',
  }

  const algorithmLabels: Record<string, string> = {
    rf: 'Random Forest',
    xgb: 'XGBoost',
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Model Comparison</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 md:grid-cols-2">
          {models.map((model) => (
            <Card key={model.id} className={model.is_active ? 'border-primary' : ''}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">
                    {algorithmLabels[model.algorithm] || model.algorithm}
                  </CardTitle>
                  {model.is_active && (
                    <Badge variant="default">Active</Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">v{model.version}</p>
              </CardHeader>
              <CardContent className="space-y-2">
                {metrics.map((metric) => (
                  <div key={metric} className="flex justify-between text-sm">
                    <span className="text-muted-foreground">{metricLabels[metric]}</span>
                    <span className="font-medium">{model[metric] != null ? formatPercent(model[metric]) : '—'}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
