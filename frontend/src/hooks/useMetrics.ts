'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { mlApi, tasksApi } from '@/lib/api'
import { ModelMetrics } from '@/types'

const TRAINING_STORAGE_KEY = 'aussieloanai_training_task'

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

export function useTrainModel() {
  const queryClient = useQueryClient()
  const [taskId, setTaskId] = useState<string | null>(null)
  const [trainingStatus, setTrainingStatus] = useState<'idle' | 'training' | 'success' | 'failure'>('idle')
  const [trainingAlgorithm, setTrainingAlgorithm] = useState<string>('')

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
        setTrainingStatus('success')
        setTaskId(null)
        clearTrainingTask()
        queryClient.invalidateQueries({ queryKey: ['modelMetrics'] })
        return false
      }
      if (status === 'FAILURE') {
        setTrainingStatus('failure')
        setTaskId(null)
        clearTrainingTask()
        return false
      }
      return 2000
    },
  })

  return { ...mutation, trainingStatus, trainingAlgorithm }
}
