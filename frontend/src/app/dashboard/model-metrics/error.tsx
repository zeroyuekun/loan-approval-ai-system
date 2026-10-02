'use client'

import { RouteError, type RouteErrorProps } from '@/components/layout/RouteError'

export default function Error(props: Pick<RouteErrorProps, 'error' | 'reset'>) {
  return (
    <RouteError
      {...props}
      title="Model Metrics Error"
      message="Failed to load model metrics."
      backHref="/dashboard"
      backLabel="Back to Dashboard"
    />
  )
}
