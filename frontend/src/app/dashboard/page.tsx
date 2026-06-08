'use client'

import { useApplications } from '@/hooks/useApplications'
import { useDashboardStats } from '@/hooks/useDashboardStats'
import { StatsCards } from '@/components/dashboard/StatsCards'
import { ApprovalRateChart } from '@/components/dashboard/ApprovalRateChart'
import { RecentApplications } from '@/components/dashboard/RecentApplications'
import { Skeleton } from '@/components/ui/skeleton'

export default function DashboardPage() {
  const { data: applicationsData, isLoading: appsLoading } = useApplications({ page_size: 5 })
  const { data: stats, isLoading: statsLoading } = useDashboardStats()

  const applications = applicationsData?.results || []

  if (appsLoading || statsLoading || !stats) {
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
        totalApplications={stats.total_applications}
        approvalRate={stats.approval_rate}
        todayDecisions={{
          count: stats.decisions_24h_count,
          p95LatencyMs: stats.decision_latency_p95_ms_24h,
        }}
        llmSpend={{
          spentUsd: stats.llm_spend_today_usd,
          capUsd: stats.llm_spend_cap_usd,
        }}
      />

      <div className="grid gap-6 md:grid-cols-2">
        <ApprovalRateChart approved={stats.approved_count} denied={stats.denied_count} />
        <RecentApplications applications={applications} />
      </div>
    </div>
  )
}
