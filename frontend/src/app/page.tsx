'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth'

export default function Home() {
  const { user, isLoading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!isLoading) {
      if (user) {
        router.replace(user.role === 'customer' ? '/apply' : '/dashboard')
      } else {
        router.replace('/login')
      }
    }
  }, [user, isLoading, router])

  return (
    <div className="flex h-screen items-center justify-center">
      <div className="animate-pulse text-lg text-muted-foreground">Loading...</div>
    </div>
  )
}
