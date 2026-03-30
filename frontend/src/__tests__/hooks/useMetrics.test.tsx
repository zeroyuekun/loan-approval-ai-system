import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { useModelMetrics, useTrainModel } from '@/hooks/useMetrics'
import { server } from '@/test/mocks/server'
import { beforeEach } from 'vitest'

const API_URL = 'http://localhost:8500/api/v1'
const TRAINING_STORAGE_KEY = 'aussieloanai_training_task'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return Wrapper
}

const mockMetrics = {
  id: 'model-1',
  algorithm: 'xgboost',
  version: '1.0.0',
  is_active: true,
  auc: 0.87,
  gini: 0.74,
  ks_statistic: 0.62,
  accuracy: 0.85,
  precision_val: 0.83,
  recall: 0.80,
  f1_score: 0.81,
  brier_score: 0.12,
  ece: 0.05,
  feature_importances: { credit_score: 0.25, annual_income: 0.20 },
  created_at: '2026-03-27T10:00:00Z',
}

beforeEach(() => {
  localStorage.clear()
})

describe('useModelMetrics', () => {
  it('fetches model metrics', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => {
        return HttpResponse.json(mockMetrics)
      }),
    )

    const { result } = renderHook(() => useModelMetrics(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data?.algorithm).toBe('xgboost')
    expect(result.current.data?.auc).toBe(0.87)
  })

  it('returns null when no model exists (404)', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => {
        return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
      }),
    )

    const { result } = renderHook(() => useModelMetrics(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    expect(result.current.data).toBeNull()
  })

  it('throws on non-404 errors', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => {
        return HttpResponse.json({ error: 'Server error' }, { status: 500 })
      }),
    )

    const { result } = renderHook(() => useModelMetrics(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
  })
})

describe('useTrainModel', () => {
  it('starts training and sets status to training', async () => {
    server.use(
      http.post(`${API_URL}/ml/models/train/`, () => {
        return HttpResponse.json({ task_id: 'task-train-1', status: 'queued' })
      }),
      http.get(`${API_URL}/tasks/:taskId/status/`, () => {
        return HttpResponse.json({ task_id: 'task-train-1', status: 'PENDING' })
      }),
    )

    const { result } = renderHook(() => useTrainModel(), {
      wrapper: createWrapper(),
    })

    expect(result.current.trainingStatus).toBe('idle')

    await act(async () => {
      result.current.mutate('xgboost')
    })

    await waitFor(() => {
      expect(result.current.trainingStatus).toBe('training')
    })
    expect(result.current.trainingAlgorithm).toBe('xgboost')
  })

  it('saves training task to localStorage', async () => {
    server.use(
      http.post(`${API_URL}/ml/models/train/`, () => {
        return HttpResponse.json({ task_id: 'task-train-2', status: 'queued' })
      }),
      http.get(`${API_URL}/tasks/:taskId/status/`, () => {
        return HttpResponse.json({ task_id: 'task-train-2', status: 'PENDING' })
      }),
    )

    const { result } = renderHook(() => useTrainModel(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate('random_forest')
    })

    await waitFor(() => {
      expect(result.current.trainingStatus).toBe('training')
    })

    const stored = JSON.parse(localStorage.getItem(TRAINING_STORAGE_KEY)!)
    expect(stored.taskId).toBe('task-train-2')
    expect(stored.algorithm).toBe('random_forest')
    expect(stored.startedAt).toBeGreaterThan(0)
  })

  it('restores training state from localStorage on mount', async () => {
    const saved = { taskId: 'task-restored', algorithm: 'xgboost', startedAt: Date.now() }
    localStorage.setItem(TRAINING_STORAGE_KEY, JSON.stringify(saved))

    server.use(
      http.get(`${API_URL}/tasks/:taskId/status/`, () => {
        return HttpResponse.json({ task_id: 'task-restored', status: 'PENDING' })
      }),
    )

    const { result } = renderHook(() => useTrainModel(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.trainingStatus).toBe('training')
    })
    expect(result.current.trainingAlgorithm).toBe('xgboost')
  })

  it('expires training task after 15 minutes', async () => {
    const expired = {
      taskId: 'task-old',
      algorithm: 'xgboost',
      startedAt: Date.now() - 16 * 60 * 1000,
    }
    localStorage.setItem(TRAINING_STORAGE_KEY, JSON.stringify(expired))

    const { result } = renderHook(() => useTrainModel(), {
      wrapper: createWrapper(),
    })

    // Should remain idle — expired task should be ignored
    await waitFor(() => {
      expect(result.current.trainingStatus).toBe('idle')
    })
    expect(localStorage.getItem(TRAINING_STORAGE_KEY)).toBeNull()
  })

  it('handles corrupt localStorage gracefully', async () => {
    localStorage.setItem(TRAINING_STORAGE_KEY, 'not-valid-json')

    const { result } = renderHook(() => useTrainModel(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.trainingStatus).toBe('idle')
    })
  })

  it('transitions to success when task completes', async () => {
    server.use(
      http.post(`${API_URL}/ml/models/train/`, () => {
        return HttpResponse.json({ task_id: 'task-success', status: 'queued' })
      }),
      http.get(`${API_URL}/tasks/:taskId/status/`, () => {
        return HttpResponse.json({ task_id: 'task-success', status: 'SUCCESS' })
      }),
    )

    const { result } = renderHook(() => useTrainModel(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate('xgboost')
    })

    await waitFor(() => {
      expect(result.current.trainingStatus).toBe('success')
    })
    expect(localStorage.getItem(TRAINING_STORAGE_KEY)).toBeNull()
  })

  it('transitions to failure when task fails', async () => {
    server.use(
      http.post(`${API_URL}/ml/models/train/`, () => {
        return HttpResponse.json({ task_id: 'task-fail', status: 'queued' })
      }),
      http.get(`${API_URL}/tasks/:taskId/status/`, () => {
        return HttpResponse.json({ task_id: 'task-fail', status: 'FAILURE' })
      }),
    )

    const { result } = renderHook(() => useTrainModel(), {
      wrapper: createWrapper(),
    })

    await act(async () => {
      result.current.mutate('xgboost')
    })

    await waitFor(() => {
      expect(result.current.trainingStatus).toBe('failure')
    })
    expect(localStorage.getItem(TRAINING_STORAGE_KEY)).toBeNull()
  })
})
