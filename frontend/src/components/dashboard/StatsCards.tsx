'use client'

import { FileText, CheckCircle, Clock, Cpu } from 'lucide-react'

interface StatsCardsProps {
  totalApplications: number
  approvalRate: number
  avgProcessingTime: string
  activeModel: string
}

export function StatsCards({ totalApplications, approvalRate, avgProcessingTime, activeModel }: StatsCardsProps) {
  const stats = [
    {
      title: 'Total Applications',
      value: totalApplications.toLocaleString('en-AU'),
      icon: FileText,
      gradient: 'from-blue-500 via-blue-600 to-indigo-600',
      shadowColor: 'shadow-blue-500/25',
      lightBg: 'bg-gradient-to-br from-blue-50 to-indigo-50',
      lightText: 'text-blue-600',
      accentBorder: 'border-blue-100',
    },
    {
      title: 'Approval Rate',
      value: `${approvalRate.toFixed(1)}%`,
      icon: CheckCircle,
      gradient: 'from-emerald-500 via-emerald-500 to-teal-600',
      shadowColor: 'shadow-emerald-500/25',
      lightBg: 'bg-gradient-to-br from-emerald-50 to-teal-50',
      lightText: 'text-emerald-600',
      accentBorder: 'border-emerald-100',
    },
    {
      title: 'Avg Processing',
      value: avgProcessingTime,
      icon: Clock,
      gradient: 'from-amber-500 via-orange-500 to-red-400',
      shadowColor: 'shadow-amber-500/25',
      lightBg: 'bg-gradient-to-br from-amber-50 to-orange-50',
      lightText: 'text-amber-600',
      accentBorder: 'border-amber-100',
    },
    {
      title: 'Active Model',
      value: activeModel,
      icon: Cpu,
      gradient: 'from-violet-500 via-purple-600 to-fuchsia-600',
      shadowColor: 'shadow-violet-500/25',
      lightBg: 'bg-gradient-to-br from-violet-50 to-fuchsia-50',
      lightText: 'text-violet-600',
      accentBorder: 'border-violet-100',
    },
  ]

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => (
        <div
          key={stat.title}
          className="group relative rounded-xl border bg-white p-5 sheen-card gradient-border"
        >
          <div className="flex items-start justify-between">
            <div className="space-y-2">
              <p className="text-sm font-medium text-muted-foreground">{stat.title}</p>
              <p className="text-2xl font-bold tracking-tight">{stat.value}</p>
            </div>
            <div className={`rounded-xl bg-gradient-to-br ${stat.gradient} p-2.5 shadow-lg ${stat.shadowColor} border border-white/20`}>
              <stat.icon className="h-5 w-5 text-white drop-shadow-sm" aria-hidden="true" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
