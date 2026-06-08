'use client'

import { FileText, CheckCircle, Clock, DollarSign } from 'lucide-react'

interface TodayDecisions {
  count: number
  p95LatencyMs: number | null
}

interface LlmSpend {
  spentUsd: number
  capUsd: number
}

interface StatsCardsProps {
  totalApplications: number
  approvalRate: number
  todayDecisions: TodayDecisions
  llmSpend: LlmSpend
}

function formatLatencySeconds(ms: number | null): string {
  if (ms === null) return 'no decisions yet'
  return `p95 ${(ms / 1000).toFixed(1)}s`
}

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`
}

export function StatsCards({
  totalApplications,
  approvalRate,
  todayDecisions,
  llmSpend,
}: StatsCardsProps) {
  // Defensive coercion. Production data is always complete (DashboardStatsView
  // returns every field), but during dev Fast Refresh a prop can momentarily be
  // undefined mid-render — and because the dashboard route has an error.tsx
  // boundary, a single `undefined.toLocaleString()` here hard-crashes the whole
  // page into the error screen until a manual reload. Falling back keeps the
  // dashboard resilient instead of all-or-nothing.
  const totalApps = totalApplications ?? 0
  const apprRate = approvalRate ?? 0
  const todayCount = todayDecisions?.count ?? 0
  const p95Ms = todayDecisions?.p95LatencyMs ?? null
  const spentUsd = llmSpend?.spentUsd ?? 0
  const capUsd = llmSpend?.capUsd ?? 0

  const spendPct = capUsd > 0 ? Math.min(100, (spentUsd / capUsd) * 100) : 0
  const spendWarning = spendPct >= 80

  const stats = [
    {
      kind: 'plain' as const,
      title: 'Total Applications',
      value: totalApps.toLocaleString('en-AU'),
      subtitle: undefined,
      icon: FileText,
      gradient: 'from-blue-500 via-blue-600 to-indigo-600',
      shadowColor: 'shadow-blue-500/25',
    },
    {
      kind: 'plain' as const,
      title: 'Approval Rate',
      value: `${apprRate.toFixed(1)}%`,
      subtitle: undefined,
      icon: CheckCircle,
      gradient: 'from-emerald-500 via-emerald-500 to-teal-600',
      shadowColor: 'shadow-emerald-500/25',
    },
    {
      kind: 'plain' as const,
      title: "Today's Decisions",
      value: todayCount.toLocaleString('en-AU'),
      subtitle: formatLatencySeconds(p95Ms),
      icon: Clock,
      gradient: 'from-amber-500 via-orange-500 to-red-400',
      shadowColor: 'shadow-amber-500/25',
    },
    {
      kind: 'spend' as const,
      title: 'LLM Spend',
      value: formatUsd(spentUsd),
      subtitle: `/ ${formatUsd(capUsd)} cap`,
      progressPct: spendPct,
      warning: spendWarning,
      icon: DollarSign,
      gradient: spendWarning
        ? 'from-rose-500 via-red-500 to-orange-600'
        : 'from-violet-500 via-purple-600 to-fuchsia-600',
      shadowColor: spendWarning ? 'shadow-rose-500/25' : 'shadow-violet-500/25',
    },
  ]

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => (
        <div
          key={stat.title}
          className="group relative rounded-xl bg-white p-5 sheen-card gradient-border"
        >
          <div className="flex items-start justify-between">
            <div className="space-y-2 min-w-0">
              <p className="text-sm font-medium text-muted-foreground">{stat.title}</p>
              <p className="text-2xl font-bold tracking-tight">{stat.value}</p>
              {stat.subtitle && (
                <p className="text-xs text-muted-foreground">{stat.subtitle}</p>
              )}
              {stat.kind === 'spend' && (
                <div
                  role="progressbar"
                  aria-valuenow={Math.round(stat.progressPct)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100 mt-2"
                >
                  <div
                    className={`h-full transition-all ${
                      stat.warning ? 'bg-rose-500' : 'bg-violet-500'
                    }`}
                    style={{ width: `${stat.progressPct}%` }}
                  />
                </div>
              )}
            </div>
            <div
              className={`rounded-xl bg-gradient-to-br ${stat.gradient} p-2.5 shadow-lg ${stat.shadowColor} border border-white/20`}
            >
              <stat.icon className="h-5 w-5 text-white drop-shadow-sm" aria-hidden="true" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
