'use client'

import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { GeneratedEmail, PaginatedResponse } from '@/types'
import { EmailPreview } from '@/components/emails/EmailPreview'
import { BiasScoreBadge } from '@/components/emails/BiasScoreBadge'
import { Skeleton } from '@/components/ui/skeleton'
import { Mail } from 'lucide-react'

export default function EmailsPage() {
  const { data, isLoading } = useQuery<PaginatedResponse<GeneratedEmail>>({
    queryKey: ['emails'],
    queryFn: async () => {
      const { data } = await api.get('/emails/')
      return data
    },
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-64" />
        ))}
      </div>
    )
  }

  const emails = data?.results || []

  if (emails.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <Mail className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No generated emails yet</p>
          <p className="text-sm text-muted-foreground">
            Emails are generated when the AI pipeline processes a loan application
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {emails.map((email) => (
        <EmailPreview key={email.id} email={email} />
      ))}
    </div>
  )
}
