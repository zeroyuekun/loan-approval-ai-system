'use client'

import { Card, CardContent } from '@/components/ui/card'
import {
  AUC_REGULATOR_FLOOR,
  KS_REGULATOR_FLOOR,
  PSI_STABLE,
  PSI_DRIFT,
} from '@/lib/benchmarks'
import type { ModelMetrics, DriftReport } from '@/types'

/**
 * KpiStrip — top-of-page lender-style headline. Four tiles with traffic-light
 * bands matching what real credit-risk dashboards (CreditVigil, DMS Anolytics,
 * Zest AI Lending Intelligence) put first: discrimination (AUC), separation
 * (KS), stability (PSI), and operational reality (approval rate). The point is
 * "is the model working today?" — answerable in one glance.
 *
 * Bands are read directly from `lib/benchmarks.ts` so the same constants drive
 * ModelCard's Performance section and this strip; reviewers cannot get
 * conflicting verdicts between the two surfaces.
 */

type Band = 'green' | 'amber' | 'red' | 'neutral'

interface KpiStripProps {
  metrics: ModelMetrics
  latestDrift?: DriftReport | null
  previousDrift?: DriftReport | null
}

interface Tile {
  label: string
  value: string
  threshold: string
  band: Band
}

const BAND_STYLES: Record<Band, { wrap: string; pip: string }> = {
  green: {
    wrap: 'border-emerald-200 bg-emerald-50/40',
    pip: 'bg-emerald-500',
  },
  amber: {
    wrap: 'border-amber-200 bg-amber-50/40',
    pip: 'bg-amber-500',
  },
  red: {
    wrap: 'border-red-200 bg-red-50/40',
    pip: 'bg-red-500',
  },
  neutral: {
    wrap: 'border-slate-200 bg-slate-50/40',
    pip: 'bg-slate-400',
  },
}

function aucBand(auc: number | null | undefined): Band {
  if (auc == null) return 'neutral'
  if (auc >= AUC_REGULATOR_FLOOR) return 'green'
  if (auc >= 0.6) return 'amber'
  return 'red'
}

function ksBand(ks: number | null | undefined): Band {
  if (ks == null) return 'neutral'
  if (ks >= KS_REGULATOR_FLOOR) return 'green'
  if (ks >= 0.2) return 'amber'
  return 'red'
}

function psiBand(psi: number | null | undefined): Band {
  if (psi == null) return 'neutral'
  if (psi < PSI_STABLE) return 'green'
  if (psi < PSI_DRIFT) return 'amber'
  return 'red'
}

function buildTiles(
  metrics: ModelMetrics,
  latestDrift: DriftReport | null | undefined,
  previousDrift: DriftReport | null | undefined,
): Tile[] {
  const auc = metrics.auc_roc ?? null
  const ks = metrics.ks_statistic ?? null
  const psi = latestDrift?.psi_score ?? null
  const approval = latestDrift?.approval_rate ?? null
  const prevApproval = previousDrift?.approval_rate ?? null

  const approvalDelta =
    approval != null && prevApproval != null
      ? approval - prevApproval
      : null
  const approvalDeltaText =
    approvalDelta != null
      ? `${approvalDelta >= 0 ? '+' : ''}${(approvalDelta * 100).toFixed(1)}pp vs prev`
      : 'no prior period'

  return [
    {
      label: 'AUC-ROC',
      value: auc != null ? auc.toFixed(3) : '—',
      threshold: `regulator floor: ${AUC_REGULATOR_FLOOR.toFixed(2)}`,
      band: aucBand(auc),
    },
    {
      label: 'KS statistic',
      value: ks != null ? ks.toFixed(3) : '—',
      threshold: `regulator floor: ${KS_REGULATOR_FLOOR.toFixed(2)}`,
      band: ksBand(ks),
    },
    {
      label: 'PSI (latest)',
      value: psi != null ? psi.toFixed(3) : '—',
      threshold: `stable < ${PSI_STABLE.toFixed(2)} · drift ≥ ${PSI_DRIFT.toFixed(2)}`,
      band: psiBand(psi),
    },
    {
      label: 'Approval rate',
      value: approval != null ? `${(approval * 100).toFixed(1)}%` : '—',
      threshold: approvalDeltaText,
      band: 'neutral',
    },
  ]
}

export function KpiStrip({ metrics, latestDrift, previousDrift }: KpiStripProps) {
  const tiles = buildTiles(metrics, latestDrift ?? null, previousDrift ?? null)

  return (
    <div
      className="grid grid-cols-2 gap-4 md:grid-cols-4"
      role="region"
      aria-label="Model KPI summary"
    >
      {tiles.map((tile) => {
        const styles = BAND_STYLES[tile.band]
        return (
          <Card key={tile.label} className={styles.wrap}>
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${styles.pip}`}
                  aria-hidden
                />
                <p className="text-xs font-medium text-muted-foreground">
                  {tile.label}
                </p>
              </div>
              <p className="text-2xl font-bold tabular-nums text-slate-900">
                {tile.value}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground leading-snug">
                {tile.threshold}
              </p>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
