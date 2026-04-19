import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { usePipelineOrchestration } from '@/hooks/usePipelineOrchestration'
import { AgentRun } from '@/types'

// Mock the underlying hooks
const mockMutateAsync = vi.fn()
const mockForceRerunMutateAsync = vi.fn()
vi.mock('@/hooks/useAgentStatus', () => ({
  useOrchestrate: () => ({
    mutateAsync: mockMutateAsync,
  }),
  useForceRerun: () => ({
    mutateAsync: mockForceRerunMutateAsync,
  }),
  useAgentRun: () => ({
    data: undefined,
  }),
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return Wrapper
}

const mockAgentRun: AgentRun = {
  id: 'run-1',
  application_id: 'loan-123',
  status: 'completed',
  steps: [],
  total_time_ms: 5000,
  error: '',
  created_at: '2025-01-15T10:00:00Z',
  updated_at: '2025-01-15T10:01:00Z',
  bias_reports: [],
  next_best_offers: [],
  marketing_emails: [],
}

describe('usePipelineOrchestration', () => {
  beforeEach(() => {
    mockMutateAsync.mockReset()
    mockForceRerunMutateAsync.mockReset()
    mockForceRerunMutateAsync.mockResolvedValue({ task_id: 'force-task-1' })
  })

  it('returns initial state correctly', () => {
    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', null),
      { wrapper: createWrapper() },
    )

    expect(result.current.orchestrating).toBe(false)
    expect(result.current.pipelineQueued).toBe(false)
    expect(result.current.pipelineError).toBeNull()
    expect(result.current.pipelineDisabled).toBe(false)
    expect(typeof result.current.handleOrchestrate).toBe('function')
  })

  it('falls back to agentRunProp when fetch returns nothing', () => {
    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', mockAgentRun),
      { wrapper: createWrapper() },
    )

    // agentRun should be the prop since useAgentRun returns undefined
    expect(result.current.agentRun).toEqual(mockAgentRun)
  })

  it('sets orchestrating to true during handleOrchestrate', async () => {
    mockMutateAsync.mockImplementation(() => new Promise((resolve) => setTimeout(resolve, 100)))

    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', null),
      { wrapper: createWrapper() },
    )

    let orchestratePromise: Promise<void>
    act(() => {
      orchestratePromise = result.current.handleOrchestrate() as unknown as Promise<void>
    })

    // orchestrating should be true while the mutation is in-flight
    expect(result.current.orchestrating).toBe(true)
    expect(result.current.pipelineDisabled).toBe(true)

    await act(async () => {
      await orchestratePromise
    })

    expect(result.current.orchestrating).toBe(false)
  })

  it('sets pipelineQueued after successful orchestration', async () => {
    mockMutateAsync.mockResolvedValue({ task_id: 'task-1' })

    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', null),
      { wrapper: createWrapper() },
    )

    await act(async () => {
      await result.current.handleOrchestrate()
    })

    expect(result.current.pipelineQueued).toBe(true)
    expect(result.current.pipelineDisabled).toBe(true)
  })

  it('sets pipelineError on orchestration failure', async () => {
    mockMutateAsync.mockRejectedValue(new Error('Rate limited'))

    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', null),
      { wrapper: createWrapper() },
    )

    await act(async () => {
      await result.current.handleOrchestrate()
    })

    expect(result.current.pipelineError).toBe('Rate limited')
    expect(result.current.pipelineQueued).toBe(false)
    expect(result.current.orchestrating).toBe(false)
  })

  it('calls onRefresh after successful orchestration', async () => {
    mockMutateAsync.mockResolvedValue({ task_id: 'task-1' })
    const onRefresh = vi.fn()

    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', null, onRefresh),
      { wrapper: createWrapper() },
    )

    await act(async () => {
      await result.current.handleOrchestrate()
    })

    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it('computes pipelineDisabled from orchestrating or pipelineQueued', async () => {
    mockMutateAsync.mockResolvedValue({ task_id: 'task-1' })

    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', null),
      { wrapper: createWrapper() },
    )

    // Initially not disabled
    expect(result.current.pipelineDisabled).toBe(false)

    // After orchestration completes, pipelineQueued is true so disabled
    await act(async () => {
      await result.current.handleOrchestrate()
    })

    expect(result.current.pipelineDisabled).toBe(true)
  })

  it('escalates to force-rerun when backend returns already_completed', async () => {
    // Backend short-circuits when a completed AgentRun exists for the
    // application. The button must auto-escalate to force-rerun so the
    // click triggers a real pipeline + new email, not a silent no-op.
    mockMutateAsync.mockResolvedValue({
      status: 'already_completed',
      existing_run_id: 'run-old',
    })

    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', null),
      { wrapper: createWrapper() },
    )

    await act(async () => {
      await result.current.handleOrchestrate()
    })

    expect(mockForceRerunMutateAsync).toHaveBeenCalledWith({
      loanId: 'loan-123',
      reason: expect.any(String),
    })
    expect(result.current.pipelineQueued).toBe(true)
    expect(result.current.pipelineError).toBeNull()
  })

  it('does NOT escalate to force-rerun on a normal successful orchestration', async () => {
    mockMutateAsync.mockResolvedValue({ task_id: 'task-1', status: 'pipeline_queued' })

    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', null),
      { wrapper: createWrapper() },
    )

    await act(async () => {
      await result.current.handleOrchestrate()
    })

    expect(mockForceRerunMutateAsync).not.toHaveBeenCalled()
    expect(result.current.pipelineQueued).toBe(true)
  })

  it('surfaces pipelineError when force-rerun escalation fails', async () => {
    mockMutateAsync.mockResolvedValue({
      status: 'already_completed',
      existing_run_id: 'run-old',
    })
    mockForceRerunMutateAsync.mockRejectedValue(new Error('Force rerun forbidden'))

    const { result } = renderHook(
      () => usePipelineOrchestration('loan-123', null),
      { wrapper: createWrapper() },
    )

    await act(async () => {
      await result.current.handleOrchestrate()
    })

    expect(mockForceRerunMutateAsync).toHaveBeenCalledTimes(1)
    expect(result.current.pipelineError).toBe('Force rerun forbidden')
    expect(result.current.pipelineQueued).toBe(false)
    expect(result.current.orchestrating).toBe(false)
  })
})
