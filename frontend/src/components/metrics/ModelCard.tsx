'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ModelMetrics } from '@/types'

interface ModelCardProps {
  metrics: ModelMetrics
}

const ALGORITHM_LABELS: Record<string, string> = {
  rf: 'Random Forest',
  xgb: 'XGBoost',
  lr: 'Logistic Regression',
}

function formatAlgorithm(alg: string | undefined): string {
  if (!alg) return 'Unknown'
  return ALGORITHM_LABELS[alg] ?? alg
}

function readSegment(metadata: ModelMetrics['training_metadata']): string {
  const seg = metadata?.training_segment
  if (typeof seg === 'string' && seg.trim().length > 0) return seg
  return 'segment unspecified'
}

/**
 * ModelCard — portfolio-facing receipt for the active model.
 *
 * Top of `/dashboard/model-metrics`. Compresses what a senior reviewer needs
 * at a glance: which segment the model was trained on, how it performs versus
 * regulator floors and an external benchmark, what evidence backs those
 * numbers, what populations it should NOT be used on, and what the production
 * posture is. The detailed gate verdicts and raw metadata live below in
 * `<ModelHealthCard />`.
 */
export function ModelCard({ metrics }: ModelCardProps) {
  const algorithm = formatAlgorithm(metrics.algorithm)
  const version = metrics.version
  const segment = readSegment(metrics.training_metadata)

  return (
    <Card>
      <CardHeader className="space-y-1">
        <CardTitle>Model Card</CardTitle>
        <p className="text-sm text-muted-foreground">
          {algorithm} <span className="text-slate-400">·</span> v{version}{' '}
          <span className="text-slate-400">·</span> {segment}
        </p>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Sections wired in B4-B9 */}
      </CardContent>
    </Card>
  )
}
