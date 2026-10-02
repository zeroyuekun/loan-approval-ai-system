'use client'

import { RouteError, type RouteErrorProps } from '@/components/layout/RouteError'

export default function Error(props: Pick<RouteErrorProps, 'error' | 'reset'>) {
  return (
    <RouteError
      {...props}
      title="Audit Log Error"
      message="Failed to load audit logs."
      backHref="/dashboard"
      backLabel="Back to Dashboard"
    />
  )
}
