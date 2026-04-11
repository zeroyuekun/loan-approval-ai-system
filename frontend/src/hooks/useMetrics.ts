'use client'

import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { mlApi, tasksApi } from '@/lib/api'
import { ModelMetrics } from '@/types'

const TRAINING_STORAGE_KEY = 'aussieloanai_training_task'

/** Exponential backoff: 2s -> 4s -> 8s -> 16s -> 30s max. Mirrors useAgentStatus. */
function nextTrainBackoff(pollCount: number): number {
  return Math.min(2000 * Math.pow(2, pollCount), 30000)
}

function saveTrainingTask(taskId: string, algorithm: string) {
  localStorage.setItem(TRAINING_STORAGE_KEY, JSON.stringify({ taskId, algorithm, startedAt: Date.now() }))
}

function loadTrainingTask(): { taskId: string; algorithm: string; startedAt: number } | null {
  try {
    const raw = localStorage.getItem(TRAINING_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    // Expire after 15 minutes
    if (Date.now() - parsed.startedAt > 15 * 60 * 1000) {
      localStorage.removeItem(TRAINING_STORAGE_KEY)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

function clearTrainingTask() {
  localStorage.removeItem(TRAINING_STORAGE_KEY)
}

export function useModelMetrics() {
  return useQuery<ModelMetrics | null>({
    queryKey: ['modelMetrics'],
    queryFn: async () => {
      try {
        const { data } = await mlApi.getMetrics()
        return data
      } catch (err: any) {
        if (err.response?.status === 404) {
          return null
        }
        throw err
      }
    },
  })
}

type TrainingStatus = 'idle' | 'training' | 'success' | 'failure' | 'skipped'

function parseTaskResult(result: unknown): Record<string, any> | null {
  if (result == null) return null
  if (typeof result === 'object') return result as Record<string, any>
  if (typeof result === 'string') {
    try {
      const parsed = JSON.parse(result)
      return typeof parsed === 'object' && parsed !== null ? parsed : null
    } catch {
      return null
    }
  }
  return null
}

export function useTrainModel() {
  const queryClient = useQueryClient()
  const [taskId, setTaskId] = useState<string | null>(null)
  const [trainingStatus, setTrainingStatus] = useState<TrainingStatus>('idle')
  const [trainingAlgorithm, setTrainingAlgorithm] = useState<string>('')
  const pollCountRef = useRef(0)

  // On mount, check if there's a training task in progress
  useEffect(() => {
    const saved = loadTrainingTask()
    if (saved) {
      setTaskId(saved.taskId)
      setTrainingAlgorithm(saved.algorithm)
      setTrainingStatus('training')
    }
  }, [])

  const mutation = useMutation({
    mutationFn: async (algorithm: string) => {
      const { data } = await mlApi.trainModel(algorithm)
      return { ...data, algorithm }
    },
    onSuccess: (data) => {
      setTaskId(data.task_id)
      setTrainingAlgorithm(data.algorithm)
      setTrainingStatus('training')
      saveTrainingTask(data.task_id, data.algorithm)
    },
  })

  const errorResponse = (mutation.error as any)?.response
  const errorStatus = errorResponse?.status as number | undefined
  const errorDetail = (errorResponse?.data?.detail || errorResponse?.data?.error) as string | undefined
  let errorMessage: string | null = null
  if (mutation.isError) {
    if (errorStatus === 429) {
      errorMessage = errorDetail
        ? `Rate limit reached: ${errorDetail}`
        : 'Training rate limit reached. Please wait a few minutes before retrying.'
    } else if (errorStatus === 409) {
      errorMessage = errorDetail
        || 'A training job is already in progress. Please wait for it to complete before starting another.'
    } else if (errorStatus === 403) {
      errorMessage = 'You do not have permission to train models. Admin role required.'
    } else if (errorStatus === 400) {
      errorMessage = errorDetail || 'Invalid training request.'
    } else {
      errorMessage = 'Model training failed. Please try again.'
    }
  }

  useQuery({
    queryKey: ['trainTaskStatus', taskId],
    queryFn: async () => {
      const { data } = await tasksApi.getStatus(taskId!)
      return data
    },
    enabled: !!taskId && trainingStatus === 'training',
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'SUCCESS') {
        // A Celery SUCCESS can still be a no-op run (the task short-circuited
        // because another training was already holding the lock). Inspect the
        // payload so we don't mislead the operator.
        const parsed = parseTaskResult(query.state.data?.result)
        if (parsed?.status === 'skipped') {
          setTrainingStatus('skipped')
        } else {
          setTrainingStatus('success')
          queryClient.invalidateQueries({ queryKey: ['modelMetrics'] })
        }
        setTaskId(null)
        clearTrainingTask()
        pollCountRef.current = 0
        return false
      }
      if (status === 'FAILURE') {
        setTrainingStatus('failure')
        setTaskId(null)
        clearTrainingTask()
        pollCountRef.current = 0
        return false
      }
      const interval = nextTrainBackoff(pollCountRef.current)
      pollCountRef.current += 1
      return interval
    },
  })

  return { ...mutation, trainingStatus, trainingAlgorithm, errorMessage }
}
