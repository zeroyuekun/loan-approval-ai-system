'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ModelMetrics } from '@/types'

interface ModelCardProps {
  metrics: ModelMetrics
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
  return (
    <Card>
      <CardHeader>
        <CardTitle>Model Card</CardTitle>
      </CardHeader>
      <CardContent>
        {/* Sections wired in B3-B9 */}
      </CardContent>
    </Card>
  )
}
