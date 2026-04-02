'use client'

import { useState, useEffect, useRef } from 'react'
import { AgentRun } from '@/types'
import { useOrchestrate, useAgentRun } from '@/hooks/useAgentStatus'

interface UsePipelineOrchestrationReturn {
  agentRun: AgentRun | null | undefined
  orchestrating: boolean
  pipelineQueued: boolean
  pipelineError: string | null
  pipelineSuccess: string | null
  pipelineDisabled: boolean
  handleOrchestrate: () => void
}

export function usePipelineOrchestration(
  applicationId: string | number,
  agentRunProp: AgentRun | null | undefined,
  onRefresh?: () => void,
): UsePipelineOrchestrationReturn {
  const orchestrate = useOrchestrate()
  const [orchestrating, setOrchestrating] = useState(false)
  const [pipelineQueued, setPipelineQueued] = useState(false)
  const [preRunAgentId, setPreRunAgentId] = useState<string | null>(null)
  const [pipelineError, setPipelineError] = useState<string | null>(null)
  const [pipelineSuccess, setPipelineSuccess] = useState<string | null>(null)
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Fetch agent run with polling awareness — keeps polling while pipeline is queued
  const { data: agentRunFetched } = useAgentRun(String(applicationId), { pipelineQueued })
  // Prefer the internally fetched run (which has polling), fall back to prop
  const agentRun = agentRunFetched ?? agentRunProp ?? null

  // Reset pipelineQueued only when a NEW agent run (different ID from
  // the one present when we clicked) reaches a terminal status.
  // This prevents the old completed run from immediately clearing the
  // queued state before Celery creates the new AgentRun.
  useEffect(() => {
    // Only react when we're actively waiting for a pipeline result
    // (preRunAgentId is set only when the user clicks "Run Pipeline")
    if (!agentRun || !preRunAgentId) return
    const isNewRun = agentRun.id !== preRunAgentId
    const isTerminal = ['completed', 'failed', 'escalated'].includes(agentRun.status)
    if (isNewRun && isTerminal) {
      setPipelineQueued(false)
      setPreRunAgentId(null)
      setPipelineError(null)
      if (agentRun.status === 'completed') {
        setPipelineSuccess('Pipeline completed successfully.')
        if (successTimerRef.current) clearTimeout(successTimerRef.current)
        successTimerRef.current = setTimeout(() => setPipelineSuccess(null), 5000)
      }
      // Refresh email + application data now that the pipeline finished
      onRefresh?.()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally depend on .id/.status, not the full object
  }, [agentRun?.id, agentRun?.status, pipelineQueued, preRunAgentId, onRefresh])

  // Safety timeout: if pipelineQueued stays true for over 5 minutes,
  // force-reset so the button isn't stuck forever.
  useEffect(() => {
    if (!pipelineQueued) return
    const timer = setTimeout(() => {
      setPipelineQueued(false)
      setPreRunAgentId(null)
    }, 300_000)
    return () => {
      clearTimeout(timer)
      if (successTimerRef.current) clearTimeout(successTimerRef.current)
    }
  }, [pipelineQueued])

  const handleOrchestrate = async () => {
    setOrchestrating(true)
    setPipelineError(null)
    setPipelineSuccess(null)
    // Snapshot the current agent run ID so we can detect when a new one appears
    setPreRunAgentId(agentRun?.id ?? null)
    try {
      await orchestrate.mutateAsync(String(applicationId))
      setPipelineQueued(true)
      onRefresh?.()
    } catch (error: any) {
      console.error('Orchestration failed:', error)
      setPipelineError(error?.message || 'Pipeline failed to start. Please try again.')
      setPreRunAgentId(null)
    } finally {
      setOrchestrating(false)
    }
  }

  const pipelineDisabled = orchestrating || pipelineQueued

  return {
    agentRun,
    orchestrating,
    pipelineQueued,
    pipelineError,
    pipelineSuccess,
    pipelineDisabled,
    handleOrchestrate,
  }
}
