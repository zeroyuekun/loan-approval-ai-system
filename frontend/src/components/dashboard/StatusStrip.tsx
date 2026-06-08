'use client'

import {
  Activity,
  Shield,
  ShieldAlert,
  Users,
} from 'lucide-react'
import type { DashboardStatusStrip, StatusLevel } from '@/types'

type IndicatorConfig = {
  key: keyof DashboardStatusStrip
  label: string
  icon: typeof Activity
}

const INDICATORS: IndicatorConfig[] = [
  { key: 'drift', label: 'Drift', icon: Activity },
  { key: 'fairness', label: 'Fairness', icon: Shield },
  { key: 'pending_review', label: 'Pending Review', icon: Users },
  { key: 'watchdog', label: 'Watchdog', icon: ShieldAlert },
]

const DOT_CLASS: Record<StatusLevel, string> = {
  none: 'bg-emerald-500',
  moderate: 'bg-amber-500',
  significant: 'bg-rose-500',
  unknown: 'bg-slate-400',
}

const BORDER_CLASS: Record<StatusLevel, string> = {
  none: 'border-emerald-200/60',
  moderate: 'border-amber-200/60',
  significant: 'border-rose-200/60',
  unknown: 'border-slate-200/60',
}

interface StatusStripProps {
  strip: DashboardStatusStrip
}

export function StatusStrip({ strip }: StatusStripProps) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {INDICATORS.map(({ key, label, icon: Icon }) => {
        const indicator = strip[key]
        const level = indicator.level
        const slaBreach =
          key === 'pending_review' && strip.pending_review.sla_breach
        return (
          <div
            key={key}
            className={`flex items-center gap-3 rounded-lg border bg-white px-3 py-2.5 ${BORDER_CLASS[level]}`}
          >
            <span
              data-testid={`status-dot-${level}`}
              aria-label={`${label} status: ${level}`}
              className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT_CLASS[level]}`}
            />
            <Icon className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2">
                <p className="text-xs font-semibold text-slate-700">{label}</p>
                {slaBreach && (
                  <span className="text-[10px] font-bold uppercase tracking-wide text-rose-600">
                    SLA breached
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground truncate" title={indicator.detail}>
                {indicator.detail}
              </p>
            </div>
          </div>
        )
      })}
    </div>
  )
}
