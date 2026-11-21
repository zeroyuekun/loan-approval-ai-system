/** Exponential polling backoff: 2s -> 4s -> 8s -> 16s -> 30s max. */
export function nextPollInterval(pollCount: number): number {
  return Math.min(2000 * Math.pow(2, pollCount), 30000)
}

/** Celery states after which a task will never change again. */
const TERMINAL_TASK_STATES = new Set(['SUCCESS', 'FAILURE', 'REVOKED'])

export function isTerminalTaskStatus(status: string | undefined): boolean {
  return status !== undefined && TERMINAL_TASK_STATES.has(status)
}

/**
 * Longest a client keeps polling one task. Celery reports PENDING forever for
 * an unknown or expired task id, so without a cap a stale id polls until the
 * tab closes.
 */
export const MAX_TASK_POLL_MS = 15 * 60 * 1000

export function taskPollingExpired(startedAt: number, now: number = Date.now()): boolean {
  return now - startedAt > MAX_TASK_POLL_MS
}
