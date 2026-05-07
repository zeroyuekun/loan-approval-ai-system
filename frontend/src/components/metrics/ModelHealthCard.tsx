'use client'

import { useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Info,
  MinusCircle,
  XCircle,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// Acceptance thresholds — surfaced inline in the card so a reader sees what
// "good" means without leaving the page. Sourced from the live codebase:
//   AUC floor 0.75 + KS floor 0.30  → mrm_dossier._performance_section
//   ECE ceiling 0.03                → model_selector.MAX_ECE_THRESHOLD
//   PSI stable 0.10 / drift 0.25    → drift_monitor + mrm_dossier._psi_section
//   Generalization gap ceiling 0.05 → trainer.py overfitting warning trigger
const THRESHOLDS = {
  AUC_FLOOR: 0.75,
  KS_FLOOR: 0.3,
  ECE_CEIL: 0.03,
  PSI_STABLE: 0.1,
  PSI_DRIFT: 0.25,
  GAP_CEIL: 0.05,
  FAIRNESS_RATIO: 0.8,
} as const

type Verdict = 'pass' | 'watch' | 'fail' | 'unknown'

interface Dimension {
  name: string
  headline: string
  detail: string
  verdict: Verdict
  // Optional: a secondary metric line (e.g. KS under Discrimination)
  secondary?: { label: string; value: string; verdict: Verdict }
}

interface ModelHealthCardProps {
  metrics: {
    auc_roc?: number | null
    ks_statistic?: number | null
    ece?: number | null
    calibration_data?: { ece?: number } | null
    fairness_metrics?: Record<string, any> | null
    training_metadata?: Record<string, any> | null
    optimal_threshold?: number | null
  }
}

// ---------------------------------------------------------------------------
// Dimension verdict computations — each function returns one row. They all
// fail-closed: if the underlying metric is missing the row renders 'unknown'
// instead of pretending the model passed.
// ---------------------------------------------------------------------------

function computeDiscrimination(m: ModelHealthCardProps['metrics']): Dimension {
  const auc = m.auc_roc ?? null
  const ks = m.ks_statistic ?? null
  if (auc == null) {
    return {
      name: 'Discrimination',
      headline: 'AUC unavailable',
      detail: 'no AUC recorded for this model',
      verdict: 'unknown',
    }
  }
  const aucVerdict: Verdict = auc >= THRESHOLDS.AUC_FLOOR ? 'pass' : 'fail'
  const aucDetail =
    aucVerdict === 'pass'
      ? `above ${THRESHOLDS.AUC_FLOOR.toFixed(2)} regulator floor`
      : `below ${THRESHOLDS.AUC_FLOOR.toFixed(2)} regulator floor`
  const dim: Dimension = {
    name: 'Discrimination',
    headline: `AUC ${auc.toFixed(3)}`,
    detail: aucDetail,
    verdict: aucVerdict,
  }
  if (ks != null) {
    dim.secondary = {
      label: 'KS',
      value: ks.toFixed(3),
      verdict: ks >= THRESHOLDS.KS_FLOOR ? 'pass' : 'fail',
    }
  }
  return dim
}

function computeCalibration(m: ModelHealthCardProps['metrics']): Dimension {
  const ece = m.calibration_data?.ece ?? m.ece ?? null
  if (ece == null) {
    return {
      name: 'Calibration',
      headline: 'ECE unavailable',
      detail: 'no calibration data — re-train with v1.9.0+ trainer',
      verdict: 'unknown',
    }
  }
  const verdict: Verdict = ece <= THRESHOLDS.ECE_CEIL ? 'pass' : 'fail'
  return {
    name: 'Calibration',
    headline: `ECE ${ece.toFixed(4)}`,
    detail:
      verdict === 'pass'
        ? `below ${THRESHOLDS.ECE_CEIL.toFixed(2)} ceiling`
        : `exceeds ${THRESHOLDS.ECE_CEIL.toFixed(2)} ceiling`,
    verdict,
  }
}

function computeStability(m: ModelHealthCardProps['metrics']): Dimension {
  const psiMap = (m.training_metadata?.psi_by_feature ?? {}) as Record<string, number>
  const values = Object.values(psiMap).filter((v): v is number => typeof v === 'number')
  if (values.length === 0) {
    return {
      name: 'Stability (PSI)',
      headline: 'no PSI data',
      detail: 'train with v1.9.9+ trainer to record per-feature PSI',
      verdict: 'unknown',
    }
  }
  const max = Math.max(...values)
  let verdict: Verdict = 'pass'
  let detail = `max feature PSI below ${THRESHOLDS.PSI_STABLE.toFixed(2)} stable boundary`
  if (max >= THRESHOLDS.PSI_DRIFT) {
    verdict = 'fail'
    detail = `at or above ${THRESHOLDS.PSI_DRIFT.toFixed(2)} significant-drift boundary`
  } else if (max >= THRESHOLDS.PSI_STABLE) {
    verdict = 'watch'
    detail = `between ${THRESHOLDS.PSI_STABLE.toFixed(2)} and ${THRESHOLDS.PSI_DRIFT.toFixed(2)} — moderate drift`
  }
  return {
    name: 'Stability (PSI)',
    headline: `max ${max.toFixed(3)}`,
    detail,
    verdict,
  }
}

function computeGeneralization(m: ModelHealthCardProps['metrics']): Dimension {
  const gap = m.training_metadata?.overfitting_gap as number | undefined
  if (typeof gap !== 'number') {
    return {
      name: 'Generalization',
      headline: 'gap unavailable',
      detail: 'no train/test gap recorded',
      verdict: 'unknown',
    }
  }
  const verdict: Verdict = gap <= THRESHOLDS.GAP_CEIL ? 'pass' : 'fail'
  return {
    name: 'Generalization',
    headline: `train→test gap ${gap.toFixed(3)}`,
    detail:
      verdict === 'pass'
        ? `below ${THRESHOLDS.GAP_CEIL.toFixed(2)} ceiling`
        : `exceeds ${THRESHOLDS.GAP_CEIL.toFixed(2)} ceiling — overfitting risk`,
    verdict,
  }
}

function computeLift(m: ModelHealthCardProps['metrics']): Dimension {
  const lift = m.training_metadata?.xgb_lift_over_baseline as number | undefined
  const baselineAuc = m.training_metadata?.baseline_auc as number | undefined
  if (typeof lift !== 'number' || typeof baselineAuc !== 'number') {
    return {
      name: 'Lift over LR',
      headline: 'baseline unavailable',
      detail: 'no logistic-regression baseline recorded',
      verdict: 'unknown',
    }
  }
  const sign = lift >= 0 ? '+' : ''
  const verdict: Verdict = lift > 0 ? 'pass' : lift === 0 ? 'watch' : 'fail'
  return {
    name: 'Lift over LR',
    headline: `${sign}${lift.toFixed(3)} AUC`,
    detail:
      verdict === 'pass'
        ? `vs LR baseline AUC ${baselineAuc.toFixed(3)}`
        : verdict === 'watch'
          ? 'no measurable improvement over LR baseline'
          : `LR baseline AUC ${baselineAuc.toFixed(3)} beats this model`,
    verdict,
  }
}

function computeFairness(m: ModelHealthCardProps['metrics']): Dimension {
  const fairness = m.fairness_metrics ?? {}
  const attrs = Object.entries(fairness)
  if (attrs.length === 0) {
    return {
      name: 'Fairness',
      headline: 'no fairness data',
      detail: 'check that the fairness evaluator ran during training',
      verdict: 'unknown',
    }
  }
  let passing = 0
  let failing: string[] = []
  for (const [attr, data] of attrs) {
    if (data && typeof data === 'object' && (data as any).passes_80_percent_rule === true) {
      passing += 1
    } else if (data && typeof data === 'object' && (data as any).passes_80_percent_rule === false) {
      failing.push(attr)
    }
  }
  const total = passing + failing.length
  const verdict: Verdict = failing.length === 0 ? 'pass' : 'fail'
  return {
    name: 'Fairness',
    headline: `${passing}/${total} attrs`,
    detail:
      verdict === 'pass'
        ? `all protected attributes meet ${(THRESHOLDS.FAIRNESS_RATIO * 100).toFixed(0)}% rule`
        : `${(THRESHOLDS.FAIRNESS_RATIO * 100).toFixed(0)}% rule fails on: ${failing.join(', ')}`,
    verdict,
  }
}

// ---------------------------------------------------------------------------
// Governance gate row — dedicated lane separate from the metric dimensions
// because gate verdicts pass the ML team's own pre-activation checklist
// (warn/block/off pattern from PRs #163-#165). A failed gate always trumps a
// passing metric, so this row drives the headline verdict if any gate failed.
// ---------------------------------------------------------------------------

interface GateInfo {
  key: 'fairness_gate' | 'promotion_gate' | 'validation_gate'
  display: string
  mode?: string
  decision?: Record<string, unknown> | null
  verdict: Verdict
  reason?: string
}

function gateVerdict(decision: Record<string, unknown> | null | undefined): Verdict {
  if (!decision) return 'unknown'
  if (decision.passed === true) return 'pass'
  if (decision.passed === false) return 'fail'
  if (decision.promoted === true) return 'pass'
  if (decision.promoted === false) return 'fail'
  if (typeof decision.result === 'string') {
    const r = (decision.result as string).toLowerCase()
    if (r === 'passed') return 'pass'
    if (r === 'blocked' || r === 'failed' || r === 'rejected') return 'fail'
    if (r === 'skipped') return 'unknown'
  }
  return 'unknown'
}

function readGates(m: ModelHealthCardProps['metrics']): GateInfo[] {
  const meta = m.training_metadata ?? {}
  const labels: Record<GateInfo['key'], string> = {
    fairness_gate: 'Fairness',
    promotion_gate: 'Promotion',
    validation_gate: 'Validation',
  }
  const gates: GateInfo[] = []
  for (const key of ['fairness_gate', 'promotion_gate', 'validation_gate'] as const) {
    const decision = (meta[key] ?? null) as Record<string, unknown> | null
    const mode = meta[`${key}_mode`] as string | undefined
    if (!decision && !mode) continue

    let reason: string | undefined
    if (decision) {
      if (typeof decision.reason === 'string') reason = decision.reason
      else if (Array.isArray(decision.reasons)) {
        const useful = (decision.reasons as unknown[]).filter(
          (r): r is string =>
            typeof r === 'string' && !r.includes('All gates passed') && !r.includes('auto-promotes'),
        )
        if (useful.length > 0) reason = useful.join('; ')
      } else if (Array.isArray(decision.failing_attributes) && decision.failing_attributes.length > 0) {
        reason = `failing on ${(decision.failing_attributes as unknown[]).join(', ')}`
      }
    }

    gates.push({
      key,
      display: labels[key],
      mode,
      decision,
      verdict: gateVerdict(decision),
      reason,
    })
  }
  return gates
}

// ---------------------------------------------------------------------------
// Headline verdict — collapses the dimension + gate matrix into a single
// pill. Fail wins over watch wins over pass. Unknown rows count as watch
// because "I don't know" should never present as healthy.
// ---------------------------------------------------------------------------

function rollupVerdict(dimensions: Dimension[], gates: GateInfo[]): {
  verdict: Verdict
  failed: number
  watch: number
  unknown: number
} {
  let failed = 0
  let watch = 0
  let unknown = 0
  for (const d of dimensions) {
    if (d.verdict === 'fail') failed += 1
    else if (d.verdict === 'watch') watch += 1
    else if (d.verdict === 'unknown') unknown += 1
  }
  for (const g of gates) {
    if (g.verdict === 'fail') failed += 1
    else if (g.verdict === 'unknown' && g.mode !== 'off') unknown += 1
  }
  let verdict: Verdict = 'pass'
  if (failed > 0) verdict = 'fail'
  else if (watch > 0 || unknown > 0) verdict = 'watch'
  return { verdict, failed, watch, unknown }
}

// ---------------------------------------------------------------------------
// Presentational primitives — kept inline so this card is self-contained.
// ---------------------------------------------------------------------------

function VerdictIcon({ verdict, className = '' }: { verdict: Verdict; className?: string }) {
  const cls = `h-4 w-4 ${className}`
  if (verdict === 'pass') return <CheckCircle2 className={`${cls} text-emerald-600`} />
  if (verdict === 'fail') return <XCircle className={`${cls} text-red-600`} />
  if (verdict === 'watch') return <AlertTriangle className={`${cls} text-amber-600`} />
  return <Info className={`${cls} text-slate-400`} />
}

function HeadlinePill({
  verdict,
  failed,
  watch,
  unknown,
}: {
  verdict: Verdict
  failed: number
  watch: number
  unknown: number
}) {
  const styles: Record<Verdict, string> = {
    pass: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
    watch: 'bg-amber-50 text-amber-800 ring-amber-200',
    fail: 'bg-red-50 text-red-800 ring-red-200',
    unknown: 'bg-slate-50 text-slate-700 ring-slate-200',
  }
  const labels: Record<Verdict, string> = {
    pass: 'GOOD',
    watch: 'WATCH',
    fail: 'FAIL',
    unknown: 'UNKNOWN',
  }
  const subParts: string[] = []
  if (failed > 0) subParts.push(`${failed} failing`)
  if (watch > 0) subParts.push(`${watch} on watch`)
  if (unknown > 0) subParts.push(`${unknown} unknown`)
  if (subParts.length === 0) subParts.push('all checks passing')
  return (
    <div className="flex items-center gap-3">
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider ring-1 ring-inset ${styles[verdict]}`}
      >
        <VerdictIcon verdict={verdict} className="!h-3.5 !w-3.5" />
        {labels[verdict]}
      </span>
      <span className="text-xs text-muted-foreground">{subParts.join(' · ')}</span>
    </div>
  )
}

function DimensionRow({ dim }: { dim: Dimension }) {
  return (
    <div className="grid grid-cols-12 gap-3 items-baseline px-6 py-2.5">
      <span className="col-span-3 text-sm font-medium text-foreground">{dim.name}</span>
      <span className="col-span-3 text-sm font-mono tabular-nums">{dim.headline}</span>
      <span className="col-span-1 flex items-center">
        <VerdictIcon verdict={dim.verdict} />
      </span>
      <span className="col-span-5 text-xs text-muted-foreground">{dim.detail}</span>
      {dim.secondary && (
        <>
          <span className="col-span-3" />
          <span className="col-span-3 text-xs font-mono tabular-nums text-muted-foreground">
            {dim.secondary.label} {dim.secondary.value}
          </span>
          <span className="col-span-1 flex items-center">
            <VerdictIcon verdict={dim.secondary.verdict} className="!h-3 !w-3" />
          </span>
          <span className="col-span-5 text-xs text-muted-foreground/80">
            {dim.secondary.verdict === 'pass'
              ? `above ${THRESHOLDS.KS_FLOOR.toFixed(2)} floor`
              : dim.secondary.verdict === 'fail'
                ? `below ${THRESHOLDS.KS_FLOOR.toFixed(2)} floor`
                : ''}
          </span>
        </>
      )}
    </div>
  )
}

function GateRow({ gates }: { gates: GateInfo[] }) {
  if (gates.length === 0) {
    return (
      <div className="grid grid-cols-12 gap-3 items-baseline px-6 py-2.5">
        <span className="col-span-3 text-sm font-medium text-foreground">Governance gates</span>
        <span className="col-span-9 text-xs text-muted-foreground">
          no gate verdicts recorded for this run
        </span>
      </div>
    )
  }
  return (
    <div className="px-6 py-2.5 space-y-1.5">
      <div className="grid grid-cols-12 gap-3 items-baseline">
        <span className="col-span-3 text-sm font-medium text-foreground">Governance gates</span>
        <span className="col-span-9 flex flex-wrap items-center gap-x-3 gap-y-1">
          {gates.map((g) => (
            <span key={g.key} className="inline-flex items-center gap-1 text-xs">
              <VerdictIcon verdict={g.verdict} className="!h-3.5 !w-3.5" />
              <span className="font-medium text-foreground">{g.display}</span>
              {g.mode && (
                <span className="text-[11px] uppercase text-muted-foreground tracking-wide">
                  ({g.mode})
                </span>
              )}
            </span>
          ))}
        </span>
      </div>
      {gates
        .filter((g) => g.reason && g.verdict !== 'pass')
        .map((g) => (
          <div key={`${g.key}-reason`} className="text-xs text-muted-foreground pl-1">
            <span className="font-medium text-foreground">{g.display}:</span> {g.reason}
          </div>
        ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Raw metadata table — collapsed by default. Mirrors the previous inline KV
// rendering on the dashboard so a power user can still see every recorded
// field without leaving the page.
// ---------------------------------------------------------------------------

function humanizeKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatRawValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4)
  }
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function RawMetadataTable({
  metadata,
  optimalThreshold,
}: {
  metadata: Record<string, unknown>
  optimalThreshold?: number | null
}) {
  const entries = Object.entries(metadata)
  if (entries.length === 0) return null
  return (
    <div className="mt-3 rounded-md border border-border overflow-hidden">
      <div className="divide-y divide-border bg-muted/10">
        {entries.map(([key, value]) => (
          <div key={key} className="grid grid-cols-2 gap-4 px-4 py-2">
            <span className="text-xs text-muted-foreground">{humanizeKey(key)}</span>
            <span
              className="text-xs font-mono text-right tabular-nums truncate"
              title={typeof value === 'object' ? JSON.stringify(value) : String(value)}
            >
              {formatRawValue(value)}
            </span>
          </div>
        ))}
        {optimalThreshold != null && (
          <div className="grid grid-cols-2 gap-4 px-4 py-2 bg-muted/40">
            <span className="text-xs font-medium text-foreground">Active Threshold</span>
            <span className="text-xs font-mono font-semibold text-right tabular-nums">
              {optimalThreshold.toFixed(2)}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Top-level card
// ---------------------------------------------------------------------------

export function ModelHealthCard({ metrics }: ModelHealthCardProps) {
  const [showRaw, setShowRaw] = useState(false)

  const dimensions: Dimension[] = [
    computeDiscrimination(metrics),
    computeCalibration(metrics),
    computeStability(metrics),
    computeGeneralization(metrics),
    computeLift(metrics),
    computeFairness(metrics),
  ]
  const gates = readGates(metrics)
  const rollup = rollupVerdict(dimensions, gates)

  const trainingSamples = metrics.training_metadata?.train_size as number | undefined
  const segment = metrics.training_metadata?.segment as string | undefined
  const classBalance = metrics.training_metadata?.class_balance as number | undefined

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1.5">
            <CardTitle className="text-base">Model Health</CardTitle>
            <p className="text-xs text-muted-foreground">
              {trainingSamples != null
                ? `Trained on ${trainingSamples.toLocaleString()} samples`
                : 'Trained on (sample size unavailable)'}
              {segment ? ` · segment: ${segment}` : ''}
              {classBalance != null ? ` · ${(classBalance * 100).toFixed(1)}% positive rate` : ''}
            </p>
          </div>
          <HeadlinePill
            verdict={rollup.verdict}
            failed={rollup.failed}
            watch={rollup.watch}
            unknown={rollup.unknown}
          />
        </div>
      </CardHeader>
      <CardContent className="px-0 space-y-0">
        <div className="divide-y divide-border border-y border-border">
          {dimensions.map((dim) => (
            <DimensionRow key={dim.name} dim={dim} />
          ))}
          <GateRow gates={gates} />
        </div>
        <div className="px-6 pt-4">
          <button
            type="button"
            onClick={() => setShowRaw((s) => !s)}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <ChevronDown
              className={`h-3.5 w-3.5 transition-transform ${showRaw ? 'rotate-180' : ''}`}
            />
            {showRaw ? 'Hide raw training metadata' : 'Show raw training metadata'}
          </button>
          {showRaw && metrics.training_metadata && (
            <RawMetadataTable
              metadata={metrics.training_metadata}
              optimalThreshold={metrics.optimal_threshold}
            />
          )}
        </div>
        {!metrics.training_metadata && (
          <div className="px-6 py-3 text-xs text-muted-foreground flex items-start gap-2">
            <MinusCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>
              No training metadata recorded for this model. Re-train with v1.9.9+ trainer to
              populate gate evidence and per-feature PSI.
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
