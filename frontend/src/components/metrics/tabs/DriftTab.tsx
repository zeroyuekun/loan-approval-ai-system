'use client'

import { DriftPanel } from '@/components/metrics/DriftPanel'
import { DriftReport } from '@/types'

export function DriftTab({ reports }: { reports: DriftReport[] }) {
  return <DriftPanel reports={reports} />
}
