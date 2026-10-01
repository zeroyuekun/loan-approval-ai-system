'use client'

import { RouteError, type RouteErrorProps } from '@/components/layout/RouteError'

export default function Error(props: Pick<RouteErrorProps, 'error' | 'reset'>) {
  return (
    <RouteError
      {...props}
      title="Dashboard Error"
      message="Something went wrong loading this page."
      backHref="/dashboard"
      backLabel="Go to Dashboard"
    />
  )
}
