'use client'

import { useQuery } from '@tanstack/react-query'
import { loansApi } from '@/lib/api'

export interface DashboardStats {
  total_applications: number
  approval_rate: number
  avg_processing_seconds: number | null
  active_model: {
    name: string
    auc: number | null
  } | null
  daily_volume: { date: string; count: number }[]
  approval_trend: { date: string; rate: number }[]
  pipeline: {
    total: number
    completed: number
    failed: number
    escalated: number
    success_rate: number
  }
}

export function useDashboardStats() {
  return useQuery<DashboardStats>({
    queryKey: ['dashboardStats'],
    queryFn: async () => {
      const { data } = await loansApi.getDashboardStats()
      return data
    },
  })
}
