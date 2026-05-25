'use client'

import type { ModelMetrics, DriftReport } from '@/types'

interface ProductionStatusTabProps {
  metrics: ModelMetrics
  driftReports: DriftReport[]
}

export function ProductionStatusTab(_props: ProductionStatusTabProps) {
  return <div data-testid="production-status-tab" className="mt-4 text-sm text-muted-foreground">Production status content — filled in Task 2.</div>
}
