'use client'

import { Button } from '@/components/ui/button'
import { XCircle } from 'lucide-react'

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex h-96 flex-col items-center justify-center gap-4 text-center">
      <XCircle className="h-12 w-12 text-red-400" />
      <div>
        <p className="font-medium">Something went wrong loading model health.</p>
        <p className="mt-1 text-sm text-muted-foreground">{error.message}</p>
      </div>
      <Button onClick={reset}>Try again</Button>
    </div>
  )
}
