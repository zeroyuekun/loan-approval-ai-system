'use client'

import { useQuery } from '@tanstack/react-query'
import { mlApi, withNotFoundFallback } from '@/lib/api'
import { DriftReport } from '@/types'

export function useDriftReports(limit?: number, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<DriftReport[]>({
    queryKey: ['driftReports', limit],
    enabled,
    queryFn: () => withNotFoundFallback(async () => (await mlApi.getDriftReports(limit)).data, []),
  })
}
