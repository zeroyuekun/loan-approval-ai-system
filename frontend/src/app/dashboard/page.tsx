'use client'

import { useApplications } from '@/hooks/useApplications'
import { StatsCards } from '@/components/dashboard/StatsCards'
import { ApprovalRateChart } from '@/components/dashboard/ApprovalRateChart'
import { RecentApplications } from '@/components/dashboard/RecentApplications'
import { ApprovalTrendChart } from '@/components/dashboard/ApprovalTrendChart'
import { PipelineStats } from '@/components/dashboard/PipelineStats'
import { useDashboardStats } from '@/hooks/useDashboardStats'
import { Skeleton } from '@/components/ui/skeleton'

export default function DashboardPage() {
  const { data: applicationsData, isLoading: appsLoading } = useApplications({ page_size: 5 })
  const { data: stats, isLoading: statsLoading } = useDashboardStats()

  const applications = applicationsData?.results || []

  const totalCount = stats?.total_applications ?? applicationsData?.count ?? 0
  const approvalRate = stats?.approval_rate ?? 0
  const avgProcessingTime = stats?.avg_processing_seconds != null
    ? `${stats.avg_processing_seconds}s`
    : '--'
  const activeModelName = stats?.active_model?.name ?? 'N/A'

  if (appsLoading || statsLoading) {
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

  const approved = stats?.approval_trend
    ? stats.approval_trend.reduce((sum, d) => sum + (d.rate > 50 ? 1 : 0), 0)
    : 0
  const denied = stats?.approval_trend
    ? stats.approval_trend.length - approved
    : 0

  // Use real decided counts from approval_rate if available
  const decidedApproved = stats
    ? Math.round((stats.approval_rate / 100) * totalCount)
    : approved
  const decidedDenied = stats
    ? totalCount - decidedApproved
    : denied

  return (
    <div className="space-y-6">
      <StatsCards
        totalApplications={totalCount}
        approvalRate={approvalRate}
        avgProcessingTime={avgProcessingTime}
        activeModel={activeModelName}
      />

      {stats?.approval_trend && stats.approval_trend.length > 0 && (
        <ApprovalTrendChart data={stats.approval_trend} />
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <ApprovalRateChart approved={decidedApproved} denied={decidedDenied} />
        <RecentApplications applications={applications} />
      </div>

      {stats?.pipeline && (
        <PipelineStats pipeline={stats.pipeline} />
      )}
    </div>
  )
}
