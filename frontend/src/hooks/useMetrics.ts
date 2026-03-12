'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { mlApi } from '@/lib/api'
import { ModelMetrics } from '@/types'

export function useModelMetrics() {
  return useQuery<ModelMetrics>({
    queryKey: ['modelMetrics'],
    queryFn: async () => {
      const { data } = await mlApi.getMetrics()
      return data
    },
  })
}

export function useTrainModel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (algorithm: string) => {
      const { data } = await mlApi.trainModel(algorithm)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['modelMetrics'] })
    },
  })
}
