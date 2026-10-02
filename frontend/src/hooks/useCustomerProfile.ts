'use client'

import { useQuery } from '@tanstack/react-query'
import { authApi } from '@/lib/api'
import type { CustomerProfile } from '@/types'

export const CUSTOMER_PROFILE_KEY = ['customerProfile'] as const

/** The signed-in customer's own profile (GET /auth/me/profile/). */
export function useCustomerProfile(options?: { enabled?: boolean; staleTime?: number }) {
  return useQuery<CustomerProfile>({
    queryKey: CUSTOMER_PROFILE_KEY,
    queryFn: async () => {
      const { data } = await authApi.getCustomerProfile()
      return data
    },
    ...options,
  })
}
