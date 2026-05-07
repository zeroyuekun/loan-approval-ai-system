'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  AUC_REGULATOR_FLOOR,
  KS_REGULATOR_FLOOR,
  ECE_CEILING,
  GMSC_AUC,
  GMSC_DATASET_LABEL,
  GMSC_REFERENCE_URL,
} from '@/lib/benchmarks'
import type { ModelMetrics } from '@/types'

interface ModelCardProps {
  metrics: ModelMetrics
}

const ALGORITHM_LABELS: Record<string, string> = {
  rf: 'Random Forest',
  xgb: 'XGBoost',
  lr: 'Logistic Regression',
}

function formatAlgorithm(alg: string | undefined): string {
  if (!alg) return 'Unknown'
  return ALGORITHM_LABELS[alg] ?? alg
}

function readSegment(metadata: ModelMetrics['training_metadata']): string {
  const seg = metadata?.training_segment
  if (typeof seg === 'string' && seg.trim().length > 0) return seg
  return 'segment unspecified'
}

// ---------------------------------------------------------------------------
// Performance row primitives — each metric headline pairs the number with a
// one-line interpretation against its acceptance threshold (AUC/KS regulator
// floors, ECE ceiling). The point is that a senior reader doesn't need to
// remember what threshold matters; the row says it inline.
// ---------------------------------------------------------------------------

interface MetricRowProps {
  label: string
  value: string
  context: string
}

function MetricRow({ label, value, context }: MetricRowProps) {
  return (
    <div className="flex items-baseline justify-between gap-4 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <span className="flex items-baseline gap-2">
        <span className="font-mono tabular-nums text-base text-slate-900">
          {value}
        </span>
        <span className="text-xs text-muted-foreground">{context}</span>
      </span>
    </div>
  )
}

function aucContext(auc: number | null | undefined): string {
  if (auc == null) return 'AUC not recorded'
  if (auc >= AUC_REGULATOR_FLOOR) {
    return `above ${AUC_REGULATOR_FLOOR.toFixed(2)} regulator floor`
  }
  return `below ${AUC_REGULATOR_FLOOR.toFixed(2)} regulator floor`
}

function ksContext(ks: number | null | undefined): string {
  if (ks == null) return 'KS not recorded'
  if (ks >= KS_REGULATOR_FLOOR) {
    return `above ${KS_REGULATOR_FLOOR.toFixed(2)} regulator floor`
  }
  return `below ${KS_REGULATOR_FLOOR.toFixed(2)} regulator floor`
}

function eceContext(ece: number | null | undefined): string {
  if (ece == null) return 'ECE not recorded'
  if (ece <= ECE_CEILING) {
    return `below ${ECE_CEILING.toFixed(2)} ceiling`
  }
  return `exceeds ${ECE_CEILING.toFixed(2)} ceiling`
}

function PerformanceSection({ metrics }: { metrics: ModelMetrics }) {
  const auc = metrics.auc_roc ?? null
  const ks = metrics.ks_statistic ?? null
  const ece = metrics.calibration_data?.ece ?? metrics.ece ?? null

  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
        Performance
      </h4>
      <div className="space-y-2 rounded-md border border-slate-100 bg-slate-50/40 p-4">
        <MetricRow
          label="AUC-ROC"
          value={auc != null ? auc.toFixed(3) : '—'}
          context={aucContext(auc)}
        />
        <MetricRow
          label="KS statistic"
          value={ks != null ? ks.toFixed(3) : '—'}
          context={ksContext(ks)}
        />
        <MetricRow
          label="ECE (calibration error)"
          value={ece != null ? ece.toFixed(4) : '—'}
          context={eceContext(ece)}
        />
        <div className="border-t border-slate-200 pt-2 text-xs text-muted-foreground">
          <span className="font-medium text-slate-600">External benchmark:</span>{' '}
          AUC{' '}
          <span className="font-mono tabular-nums text-slate-700">
            {GMSC_AUC.toFixed(3)}
          </span>{' '}
          on{' '}
          <a
            className="underline decoration-dotted underline-offset-2 hover:text-slate-700"
            href={GMSC_REFERENCE_URL}
            target="_blank"
            rel="noreferrer noopener"
          >
            {GMSC_DATASET_LABEL}
          </a>
        </div>
      </div>
    </section>
  )
}

/**
 * ModelCard — portfolio-facing receipt for the active model.
 *
 * Top of `/dashboard/model-metrics`. Compresses what a senior reviewer needs
 * at a glance: which segment the model was trained on, how it performs versus
 * regulator floors and an external benchmark, what evidence backs those
 * numbers, what populations it should NOT be used on, and what the production
 * posture is. The detailed gate verdicts and raw metadata live below in
 * `<ModelHealthCard />`.
 */
export function ModelCard({ metrics }: ModelCardProps) {
  const algorithm = formatAlgorithm(metrics.algorithm)
  const version = metrics.version
  const segment = readSegment(metrics.training_metadata)

  return (
    <Card>
      <CardHeader className="space-y-1">
        <CardTitle>Model Card</CardTitle>
        <p className="text-sm text-muted-foreground">
          {algorithm} <span className="text-slate-400">·</span> v{version}{' '}
          <span className="text-slate-400">·</span> {segment}
        </p>
      </CardHeader>
      <CardContent className="space-y-6">
        <PerformanceSection metrics={metrics} />
        {/* Sections wired in B5-B9 */}
      </CardContent>
    </Card>
  )
}
