'use client'

import type { ModelCard } from '@/types'

interface GovernanceTabProps {
  card: ModelCard | null | undefined
}

export function GovernanceTab(_props: GovernanceTabProps) {
  return <div data-testid="governance-tab" className="mt-4 text-sm text-muted-foreground">Governance content — filled in Task 4.</div>
}
