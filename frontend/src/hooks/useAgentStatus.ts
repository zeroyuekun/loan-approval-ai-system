'use client'

import { useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi, tasksApi } from '@/lib/api'
import { AgentRun, TaskStatus } from '@/types'

/** Exponential backoff: 2s -> 4s -> 8s -> 16s -> 30s max */
function nextBackoff(pollCount: number): number {
  return Math.min(2000 * Math.pow(2, pollCount), 30000)
}

export function useAgentRun(loanId: string, options?: { pipelineQueued?: boolean }) {
  const pipelineQueued = options?.pipelineQueued ?? false
  const pollCountRef = useRef(0)

  return useQuery<AgentRun>({
    queryKey: ['agentRun', loanId],
    queryFn: async () => {
      const { data } = await agentsApi.getRun(loanId)
      // Reset backoff when status changes to terminal
      if (data.status !== 'pending' && data.status !== 'running') {
        pollCountRef.current = 0
      }
      return data
    },
    enabled: !!loanId,
    retry: false,
    gcTime: 30_000, // 30s: polled data, drop fast after unmount
    refetchInterval: (query) => {
      const status = query.state.data?.status
      // Keep polling while the run is active, with exponential backoff
      if (status === 'pending' || status === 'running') {
        const interval = nextBackoff(pollCountRef.current)
        pollCountRef.current += 1
        return interval
      }
      // Also keep polling if the frontend knows a new run is expected
      // (the current data is the OLD completed run; Celery hasn't created the new one yet)
      if (pipelineQueued) {
        const interval = nextBackoff(pollCountRef.current)
        pollCountRef.current += 1
        return interval
      }
      pollCountRef.current = 0
      return false
    },
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
      queryClient.invalidateQueries({ queryKey: ['email', loanId] })
    },
    onError: (error: any) => {
      // Surface throttle errors so the button doesn't just silently fail
      if (error?.response?.status === 429) {
        const retryAfter = error.response.headers?.['retry-after']
        const waitSec = retryAfter ? parseInt(retryAfter, 10) : 60
        throw new Error(`Rate limited — try again in ${waitSec}s`)
      }
      if (error?.code === 'ECONNABORTED' || error?.message?.includes('timeout')) {
        throw new Error('Request timed out — the backend may be starting up. Please try again.')
      }
      throw error
    },
  })
}

export function useTaskStatus(taskId: string, options?: { enabled?: boolean }) {
  const taskPollCountRef = useRef(0)

  return useQuery<TaskStatus>({
    queryKey: ['taskStatus', taskId],
    queryFn: async () => {
      const { data } = await tasksApi.getStatus(taskId)
      if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
        taskPollCountRef.current = 0
      }
      return data
    },
    enabled: !!taskId && (options?.enabled ?? true),
    gcTime: 30_000, // 30s: polled data, drop fast after unmount
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'SUCCESS' || status === 'FAILURE') {
        taskPollCountRef.current = 0
        return false
      }
      const interval = nextBackoff(taskPollCountRef.current)
      taskPollCountRef.current += 1
      return interval
    },
  })
}
