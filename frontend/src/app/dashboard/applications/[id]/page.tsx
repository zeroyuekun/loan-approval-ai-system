'use client'

import { useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useApplication } from '@/hooks/useApplications'
import { useAuth } from '@/lib/auth'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { emailApi, loansApi } from '@/lib/api'
import { ApplicationDetail } from '@/components/applications/ApplicationDetail'
import { Skeleton } from '@/components/ui/skeleton'
import { GeneratedEmail } from '@/types'

export default function ApplicationDetailPage() {
  const params = useParams()
  const id = params.id as string
  const router = useRouter()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const isAdmin = user?.role === 'admin'

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

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['application', id] })
    queryClient.invalidateQueries({ queryKey: ['email', id] })
    queryClient.invalidateQueries({ queryKey: ['agentRun', id] })
  }

  const handleDelete = async () => {
    setIsDeleting(true)
    try {
      await loansApi.delete(id)
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      router.push('/dashboard/applications')
    } catch (error) {
      console.error('Failed to delete application:', error)
      setIsDeleting(false)
      setShowDeleteConfirm(false)
    }
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
      onRefresh={handleRefresh}
      onDelete={isAdmin ? handleDelete : undefined}
      isDeleting={isDeleting}
      showDeleteConfirm={showDeleteConfirm}
      onDeleteConfirmToggle={setShowDeleteConfirm}
    />
  )
}
