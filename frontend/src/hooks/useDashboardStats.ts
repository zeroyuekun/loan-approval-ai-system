'use client'

import { useQuery } from '@tanstack/react-query'
import { loansApi } from '@/lib/api'
import type { DashboardStats } from '@/types'

/**
 * Fetches the operator-grade dashboard stats payload from
 * /api/v1/loans/dashboard-stats/, including the rolling-24h decision
 * latency percentiles and today's LLM spend.
 *
 * Cached for 60 seconds server-side (DashboardStatsView); a 30s client
 * staleTime avoids redundant fetches between visits.
 */
export function useDashboardStats() {
  return useQuery<DashboardStats>({
    queryKey: ['dashboard-stats'],
    queryFn: async () => {
      const { data } = await loansApi.getDashboardStats()
      return data
    },
    staleTime: 30 * 1000,
  })
}
