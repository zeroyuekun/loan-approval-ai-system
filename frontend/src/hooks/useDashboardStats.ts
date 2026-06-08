'use client'

import { useQuery } from '@tanstack/react-query'
import { loansApi } from '@/lib/api'
import type { DashboardStats } from '@/types'

/**
 * Fetches the operator-grade dashboard stats payload from
 * /api/v1/loans/dashboard-stats/. Includes the rolling-24h decision
 * latency percentiles and today's LLM spend, both added in PR-1 of
 * the dashboard persona refit.
 *
 * Cached for 30 seconds server-side (DashboardStatsView), so a 30s
 * staleTime on the client side avoids redundant fetches.
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
