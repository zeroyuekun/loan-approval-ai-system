'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { loansApi, type LoanPayload } from '@/lib/api'
import { LoanApplication, PaginatedResponse } from '@/types'

// The loans endpoints answer by role: staff get LoanApplication, customers get
// CustomerLoanApplication (masked money and score), so customer pages pass it as T.
export function useApplications<T = LoanApplication>(params?: Record<string, any>) {
  return useQuery<PaginatedResponse<T>>({
    queryKey: ['applications', params],
    queryFn: async () => {
      const { data } = await loansApi.list(params)
      return data
    },
  })
}

export function useApplication<T = LoanApplication>(
  id: string,
  options?: { refetchInterval?: number | false | ((query: { state: { data?: T } }) => number | false) },
) {
  return useQuery<T>({
    queryKey: ['application', id],
    queryFn: async () => {
      const { data } = await loansApi.get(id)
      return data
    },
    enabled: !!id,
    refetchInterval: options?.refetchInterval,
  })
}

export function useCreateApplication() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (formData: LoanPayload) => {
      const { data } = await loansApi.create(formData)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
    },
  })
}
