import { Badge } from '@/components/ui/badge'
import { getDisplayStatus } from '@/lib/utils'

interface ApplicationStatusBadgeProps {
  status: string
  decision?: { decision: string } | null
  /** Expose the badge as a live status region (used on the customer status page). */
  announce?: boolean
}

/** Status pill for a loan application; shows the ML decision while status is 'review'. */
export function ApplicationStatusBadge({ status, decision, announce = false }: ApplicationStatusBadgeProps) {
  const { label, color } = getDisplayStatus(status, decision)
  const a11y = announce ? { role: 'status', 'aria-label': `Application status: ${label}` } : {}
  return (
    <Badge className={color} variant="outline" {...a11y}>
      {label}
    </Badge>
  )
}
