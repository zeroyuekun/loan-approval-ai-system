'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { loansApi } from '@/lib/api'
import { LoanApplication, PaginatedResponse } from '@/types'

export function useApplications(params?: Record<string, any>) {
  return useQuery<PaginatedResponse<LoanApplication>>({
    queryKey: ['applications', params],
    queryFn: async () => {
      const { data } = await loansApi.list(params)
      return data
    },
  })
}

export function useApplication(id: string) {
  return useQuery<LoanApplication>({
    queryKey: ['application', id],
    queryFn: async () => {
      const { data } = await loansApi.get(id)
      return data
    },
    enabled: !!id,
  })
}

export function useCreateApplication() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (formData: any) => {
      const { data } = await loansApi.create(formData)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
    },
  })
}

export function useUpdateApplication() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, data: updateData }: { id: string; data: any }) => {
      const { data } = await loansApi.update(id, updateData)
      return data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      queryClient.invalidateQueries({ queryKey: ['application', data.id] })
    },
  })
}
