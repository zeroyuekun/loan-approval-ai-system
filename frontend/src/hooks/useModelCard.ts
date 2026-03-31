'use client'

import { useQuery } from '@tanstack/react-query'
import { mlApi } from '@/lib/api'
import { ModelCard } from '@/types'

export function useModelCard() {
  return useQuery<ModelCard | null>({
    queryKey: ['modelCard'],
    queryFn: async () => {
      try {
        const { data } = await mlApi.getModelCard()
        return data.model_card
      } catch (err: any) {
        if (err.response?.status === 404) {
          return null
        }
        throw err
      }
    },
  })
}
