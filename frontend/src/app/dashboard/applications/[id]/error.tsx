'use client'

import { RouteError, type RouteErrorProps } from '@/components/layout/RouteError'

export default function Error(props: Pick<RouteErrorProps, 'error' | 'reset'>) {
  return (
    <RouteError
      {...props}
      title="Application Error"
      message="Failed to load application details."
      backHref="/dashboard/applications"
      backLabel="Back to Applications"
    />
  )
}
