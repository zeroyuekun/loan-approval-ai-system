'use client'

import { useQuery } from '@tanstack/react-query'
import { mlApi, withNotFoundFallback } from '@/lib/api'
import { DriftReport } from '@/types'

export function useDriftReports(limit?: number) {
  return useQuery<DriftReport[]>({
    queryKey: ['driftReports', limit],
    queryFn: () => withNotFoundFallback(async () => (await mlApi.getDriftReports(limit)).data, []),
  })
}
