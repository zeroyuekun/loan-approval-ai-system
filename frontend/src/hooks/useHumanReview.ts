'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi } from '@/lib/api'
import { AgentRun, PaginatedResponse } from '@/types'

export function useEscalatedRuns(params?: { page?: number }) {
  return useQuery<PaginatedResponse<AgentRun>>({
    queryKey: ['escalated-runs', params],
    queryFn: async () => {
      const { data } = await agentsApi.getRuns({ ...params, status: 'escalated' })
      return data
    },
  })
}

export function useSubmitReview() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      runId,
      action,
      note,
    }: {
      runId: string
      action: 'approve' | 'deny' | 'regenerate'
      note?: string
    }) => {
      const { data } = await agentsApi.submitReview(runId, { action, note })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['escalated-runs'] })
      queryClient.invalidateQueries({ queryKey: ['applications'] })
    },
  })
}
