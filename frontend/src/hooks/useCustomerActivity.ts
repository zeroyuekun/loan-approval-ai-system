'use client'

import { useQuery } from '@tanstack/react-query'
import { authApi } from '@/lib/api'
import type { CustomerActivity } from '@/types'

/** Staff view of one customer's activity (GET /auth/customers/:id/activity/). */
export function useCustomerActivity(userId: number) {
  return useQuery<CustomerActivity>({
    queryKey: ['customerActivity', userId],
    queryFn: async () => {
      const { data } = await authApi.getCustomerActivity(userId)
      return data
    },
    enabled: !isNaN(userId),
  })
}
