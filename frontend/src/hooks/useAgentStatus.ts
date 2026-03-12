'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi, tasksApi } from '@/lib/api'
import { AgentRun, TaskStatus } from '@/types'

export function useAgentRun(loanId: string) {
  return useQuery<AgentRun>({
    queryKey: ['agentRun', loanId],
    queryFn: async () => {
      const { data } = await agentsApi.getRun(loanId)
      return data
    },
    enabled: !!loanId,
  })
}

export function useOrchestrate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (loanId: string) => {
      const { data } = await agentsApi.orchestrate(loanId)
      return data
    },
    onSuccess: (_data, loanId) => {
      queryClient.invalidateQueries({ queryKey: ['agentRun', loanId] })
      queryClient.invalidateQueries({ queryKey: ['application', loanId] })
    },
  })
}

export function useTaskStatus(taskId: string, options?: { enabled?: boolean }) {
  return useQuery<TaskStatus>({
    queryKey: ['taskStatus', taskId],
    queryFn: async () => {
      const { data } = await tasksApi.getStatus(taskId)
      return data
    },
    enabled: !!taskId && (options?.enabled ?? true),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'SUCCESS' || status === 'FAILURE') return false
      return 2000
    },
  })
}
