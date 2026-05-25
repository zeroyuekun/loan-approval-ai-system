'use client'

import type { ModelMetrics, ModelCard } from '@/types'

interface ModelDetailTabProps {
  metrics: ModelMetrics
  card: ModelCard | null | undefined
}

export function ModelDetailTab(_props: ModelDetailTabProps) {
  return <div data-testid="model-detail-tab" className="mt-4 text-sm text-muted-foreground">Model detail content — filled in Task 3.</div>
}
