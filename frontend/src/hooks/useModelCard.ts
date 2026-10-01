'use client'

import { useQuery } from '@tanstack/react-query'
import { mlApi, withNotFoundFallback } from '@/lib/api'
import { ModelCard } from '@/types'

export function useModelCard() {
  return useQuery<ModelCard | null>({
    queryKey: ['modelCard'],
    queryFn: () => withNotFoundFallback(async () => (await mlApi.getModelCard()).data.model_card, null),
  })
}
