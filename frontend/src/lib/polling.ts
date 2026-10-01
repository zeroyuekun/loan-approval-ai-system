/** Exponential polling backoff: 2s -> 4s -> 8s -> 16s -> 30s max. */
export function nextPollInterval(pollCount: number): number {
  return Math.min(2000 * Math.pow(2, pollCount), 30000)
}
