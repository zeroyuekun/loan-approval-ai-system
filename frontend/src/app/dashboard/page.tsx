'use client'

import { useApplications } from '@/hooks/useApplications'
import { StatsCards } from '@/components/dashboard/StatsCards'
import { ApprovalRateChart } from '@/components/dashboard/ApprovalRateChart'
import { RecentApplications } from '@/components/dashboard/RecentApplications'
import { useModelMetrics } from '@/hooks/useMetrics'
import { Skeleton } from '@/components/ui/skeleton'

export default function DashboardPage() {
  const { data: applicationsData, isLoading: appsLoading } = useApplications({ page_size: 5 })
  const { data: metrics } = useModelMetrics()

  const applications = applicationsData?.results || []
  const totalCount = applicationsData?.count || 0

  const approved = applications.filter((a) => a.status === 'approved').length
  const denied = applications.filter((a) => a.status === 'denied').length
  const approvalRate = totalCount > 0 ? (approved / Math.max(approved + denied, 1)) * 100 : 0

  const activeModelName = metrics
    ? `${metrics.algorithm === 'rf' ? 'Random Forest' : 'XGBoost'} v${metrics.version}`
    : 'N/A'

  if (appsLoading) {
    return (
      <div className="space-y-6">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <StatsCards
        totalApplications={totalCount}
        approvalRate={approvalRate}
        avgProcessingTime="2.3s"
        activeModel={activeModelName}
      />

      <div className="grid gap-6 md:grid-cols-2">
        <ApprovalRateChart approved={approved} denied={denied} />
        <RecentApplications applications={applications} />
      </div>
    </div>
  )
}
