'use client'

import { useParams } from 'next/navigation'
import { useApplication } from '@/hooks/useApplications'
import { useAgentRun } from '@/hooks/useAgentStatus'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { emailApi } from '@/lib/api'
import { ApplicationDetail } from '@/components/applications/ApplicationDetail'
import { Skeleton } from '@/components/ui/skeleton'
import { GeneratedEmail } from '@/types'

export default function ApplicationDetailPage() {
  const params = useParams()
  const id = params.id as string
  const queryClient = useQueryClient()

  const { data: application, isLoading: appLoading } = useApplication(id)

  const { data: email } = useQuery<GeneratedEmail>({
    queryKey: ['email', id],
    queryFn: async () => {
      const { data } = await emailApi.get(id)
      return data
    },
    enabled: !!id,
    retry: false,
  })

  const { data: agentRun } = useAgentRun(id)

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['application', id] })
    queryClient.invalidateQueries({ queryKey: ['email', id] })
    queryClient.invalidateQueries({ queryKey: ['agentRun', id] })
  }

  if (appLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (!application) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-muted-foreground">Application not found</p>
      </div>
    )
  }

  return (
    <ApplicationDetail
      application={application}
      email={email || null}
      agentRun={agentRun || null}
      onRefresh={handleRefresh}
    />
  )
}
