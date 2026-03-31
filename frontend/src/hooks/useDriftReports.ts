'use client'

import { useQuery } from '@tanstack/react-query'
import { mlApi } from '@/lib/api'
import { DriftReport } from '@/types'

export function useDriftReports(limit?: number) {
  return useQuery<DriftReport[]>({
    queryKey: ['driftReports', limit],
    queryFn: async () => {
      try {
        const { data } = await mlApi.getDriftReports(limit)
        return data
      } catch (err: any) {
        if (err.response?.status === 404) {
          return []
        }
        throw err
      }
    },
  })
}
