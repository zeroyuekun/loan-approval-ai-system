'use client'

import { useState, useEffect, useRef } from 'react'
import { AgentRun } from '@/types'
import { useOrchestrate, useAgentRun, useForceRerun } from '@/hooks/useAgentStatus'

interface UsePipelineOrchestrationReturn {
  agentRun: AgentRun | null | undefined
  orchestrating: boolean
  pipelineQueued: boolean
  pipelineError: string | null
  pipelineSuccess: string | null
  pipelineDisabled: boolean
  // Promise<void> so callers can await and react to orchestration failures
  handleOrchestrate: () => Promise<void>
  /** True while the user is asked to confirm a forced re-run and give a reason. */
  forceRerunPrompt: boolean
  forceRerunPending: boolean
  forceRerunError: string | null
  confirmForceRerun: (reason: string) => Promise<void>
  cancelForceRerun: () => void
}

export function usePipelineOrchestration(
  applicationId: string | number,
  agentRunProp: AgentRun | null | undefined,
  onRefresh?: () => void,
): UsePipelineOrchestrationReturn {
  const orchestrate = useOrchestrate()
  const forceRerun = useForceRerun()
  const [orchestrating, setOrchestrating] = useState(false)
  const [pipelineQueued, setPipelineQueued] = useState(false)
  const [preRunAgentId, setPreRunAgentId] = useState<string | null>(null)
  const [pipelineError, setPipelineError] = useState<string | null>(null)
  const [pipelineSuccess, setPipelineSuccess] = useState<string | null>(null)
  const [forceRerunPrompt, setForceRerunPrompt] = useState(false)
  const [forceRerunPending, setForceRerunPending] = useState(false)
  const [forceRerunError, setForceRerunError] = useState<string | null>(null)
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
    // Only react while waiting for a queued pipeline. pipelineQueued is the
    // waiting flag, not preRunAgentId: that is null when the application had
    // no run before the click, and then any run that appears is the new one.
    if (!agentRun || !pipelineQueued) return
    const isNewRun = preRunAgentId === null || agentRun.id !== preRunAgentId
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
      const result = await orchestrate.mutateAsync(String(applicationId))
      // Backend short-circuits with {status:"already_completed"} when a
      // completed AgentRun exists. A fresh run means a forced re-run, which
      // regenerates the decision and the customer email and is audited with
      // a reason, so ask the staff member to confirm and type that reason
      // instead of escalating on a single click.
      if (result?.status === 'already_completed') {
        setForceRerunError(null)
        setForceRerunPrompt(true)
        return
      }
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

  const confirmForceRerun = async (reason: string) => {
    const trimmed = reason.trim()
    if (!trimmed) return
    setForceRerunPending(true)
    setForceRerunError(null)
    try {
      await forceRerun.mutateAsync({ loanId: String(applicationId), reason: trimmed })
      setForceRerunPrompt(false)
      setPipelineQueued(true)
      onRefresh?.()
    } catch (error: any) {
      setForceRerunError(error?.message || 'Force rerun failed. Please try again.')
    } finally {
      setForceRerunPending(false)
    }
  }

  const cancelForceRerun = () => {
    setForceRerunPrompt(false)
    setForceRerunError(null)
    setPreRunAgentId(null)
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
    forceRerunPrompt,
    forceRerunPending,
    forceRerunError,
    confirmForceRerun,
    cancelForceRerun,
  }
}
