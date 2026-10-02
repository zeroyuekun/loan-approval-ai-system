'use client'

import { useRef } from 'react'
import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { agentsApi } from '@/lib/api'
import { nextPollInterval } from '@/lib/polling'
import { AgentRun } from '@/types'

/** Queries that change once a pipeline run is (re)started for a loan. */
export function invalidateRunQueries(queryClient: QueryClient, loanId: string) {
  queryClient.invalidateQueries({ queryKey: ['agentRun', loanId] })
  queryClient.invalidateQueries({ queryKey: ['application', loanId] })
  queryClient.invalidateQueries({ queryKey: ['email', loanId] })
}

function rateLimitedError(error: any): Error {
  const retryAfter = error.response.headers?.['retry-after']
  const waitSec = retryAfter ? parseInt(retryAfter, 10) : 60
  return new Error(`Rate limited — try again in ${waitSec}s`)
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
      // Keep polling (with exponential backoff) while the run is active, or
      // while the frontend knows a new run is expected (the current data is
      // the OLD completed run; Celery hasn't created the new one yet).
      if (status === 'pending' || status === 'running' || pipelineQueued) {
        const interval = nextPollInterval(pollCountRef.current)
        pollCountRef.current += 1
        return interval
      }
      pollCountRef.current = 0
      return false
    },
  })
}

/** Friendly messages for orchestrate failures; anything else passes through. */
function orchestrateError(error: any): Error {
  // Surface throttle errors so the button doesn't just silently fail
  if (error?.response?.status === 429) return rateLimitedError(error)
  if (error?.code === 'ECONNABORTED' || error?.message?.includes('timeout')) {
    return new Error('Request timed out — the backend may be starting up. Please try again.')
  }
  return error
}

function forceRerunError(error: any): Error {
  const status = error?.response?.status
  if (status === 403) return new Error('Force rerun requires staff role.')
  if (status === 400) return new Error(error?.response?.data?.detail || 'A reason is required.')
  if (status === 429) return rateLimitedError(error)
  return error
}

// Errors are mapped inside mutationFn, not onError: TanStack Query ignores a
// value thrown from onError (it becomes an unhandled rejection) and callers
// still receive the original AxiosError.
export function useOrchestrate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (loanId: string) => {
      try {
        const { data } = await agentsApi.orchestrate(loanId)
        return data
      } catch (error) {
        throw orchestrateError(error)
      }
    },
    onSuccess: (_data, loanId) => invalidateRunQueries(queryClient, loanId),
  })
}

export function useForceRerun() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ loanId, reason }: { loanId: string; reason: string }) => {
      try {
        const { data } = await agentsApi.forceRerun(loanId, reason)
        return data
      } catch (error) {
        throw forceRerunError(error)
      }
    },
    onSuccess: (_data, variables) => invalidateRunQueries(queryClient, variables.loanId),
  })
}
