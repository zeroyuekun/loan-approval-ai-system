'use client'

import { useState } from 'react'
import { ChevronDown, Info } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// Reference thresholds — shown next to each metric so a reader can compare
// the synthetic-data values to industry guidelines, but no pass/fail verdict
// is rendered. The model is trained on synthetic AU data calibrated against
// public benchmarks (see backend/docs/CALIBRATION_SOURCES.md); pass/fail
// claims would overreach beyond what the training distribution supports.
//
// Sources:
//   AUC floor 0.75 + KS floor 0.30  → mrm_dossier._performance_section
//   ECE ceiling 0.03                → model_selector.MAX_ECE_THRESHOLD
//   PSI stable 0.10 / drift 0.25    → drift_monitor + mrm_dossier._psi_section
//   Generalization gap ceiling 0.05 → trainer.py overfitting warning trigger
const REFERENCE = {
  AUC_FLOOR: 0.75,
  KS_FLOOR: 0.3,
  ECE_CEIL: 0.03,
  PSI_STABLE: 0.1,
  PSI_DRIFT: 0.25,
  GAP_CEIL: 0.05,
  FAIRNESS_RATIO: 0.8,
} as const

interface Dimension {
  name: string
  headline: string
  detail: string
  // Optional secondary metric on the same dimension (e.g. KS under Discrimination)
  secondary?: { label: string; value: string; detail: string }
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
// Dimension computations — each function returns one row. Empty/missing data
// renders an explicit "not recorded" string rather than a fabricated value.
// ---------------------------------------------------------------------------

function computeDiscrimination(m: ModelHealthCardProps['metrics']): Dimension {
  const auc = m.auc_roc ?? null
  const ks = m.ks_statistic ?? null
  if (auc == null) {
    return {
      name: 'Discrimination',
      headline: 'AUC not recorded',
      detail: 'no AUC available for this model',
    }
  }
  const dim: Dimension = {
    name: 'Discrimination',
    headline: `AUC ${auc.toFixed(3)}`,
    detail: `industry floor: ${REFERENCE.AUC_FLOOR.toFixed(2)}`,
  }
  if (ks != null) {
    dim.secondary = {
      label: 'KS',
      value: ks.toFixed(3),
      detail: `industry floor: ${REFERENCE.KS_FLOOR.toFixed(2)}`,
    }
  }
  return dim
}

function computeCalibration(m: ModelHealthCardProps['metrics']): Dimension {
  const ece = m.calibration_data?.ece ?? m.ece ?? null
  if (ece == null) {
    return {
      name: 'Calibration',
      headline: 'ECE not recorded',
      detail: 'no calibration data — re-train with v1.9.0+ trainer',
    }
  }
  return {
    name: 'Calibration',
    headline: `ECE ${ece.toFixed(4)}`,
    detail: `industry ceiling: ${REFERENCE.ECE_CEIL.toFixed(2)}`,
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
    }
  }
  const max = Math.max(...values)
  return {
    name: 'Stability (PSI)',
    headline: `max ${max.toFixed(3)}`,
    detail: `stable < ${REFERENCE.PSI_STABLE.toFixed(2)} · significant drift ≥ ${REFERENCE.PSI_DRIFT.toFixed(2)}`,
  }
}

function computeGeneralization(m: ModelHealthCardProps['metrics']): Dimension {
  const gap = m.training_metadata?.overfitting_gap as number | undefined
  if (typeof gap !== 'number') {
    return {
      name: 'Generalization',
      headline: 'gap not recorded',
      detail: 'no train/test gap available',
    }
  }
  return {
    name: 'Generalization',
    headline: `train→test gap ${gap.toFixed(3)}`,
    detail: `industry ceiling: ${REFERENCE.GAP_CEIL.toFixed(2)}`,
  }
}

function computeLift(m: ModelHealthCardProps['metrics']): Dimension {
  const lift = m.training_metadata?.xgb_lift_over_baseline as number | undefined
  const baselineAuc = m.training_metadata?.baseline_auc as number | undefined
  if (typeof lift !== 'number' || typeof baselineAuc !== 'number') {
    return {
      name: 'Lift over LR',
      headline: 'baseline not recorded',
      detail: 'no logistic-regression baseline available',
    }
  }
  const sign = lift >= 0 ? '+' : ''
  return {
    name: 'Lift over LR',
    headline: `${sign}${lift.toFixed(3)} AUC`,
    detail: `vs LR baseline AUC ${baselineAuc.toFixed(3)}`,
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
  const detail =
    failing.length === 0
      ? `industry rule: DI ≥ ${REFERENCE.FAIRNESS_RATIO.toFixed(2)} on all attributes`
      : `slices below ${(REFERENCE.FAIRNESS_RATIO * 100).toFixed(0)}% rule: ${failing.join(', ')}`
  return {
    name: 'Fairness',
    headline: `${passing}/${total} attrs above 80% rule`,
    detail,
  }
}

// ---------------------------------------------------------------------------
// Governance gate row — shows recorded gate verdicts as plain text, no icons.
// ---------------------------------------------------------------------------

interface GateInfo {
  key: 'fairness_gate' | 'promotion_gate' | 'validation_gate'
  display: string
  mode?: string
  decision?: Record<string, unknown> | null
  reason?: string
  result?: string
}

function gateResultText(decision: Record<string, unknown> | null | undefined): string | undefined {
  if (!decision) return undefined
  if (decision.passed === true) return 'passed'
  if (decision.passed === false) return 'rejected'
  if (decision.promoted === true) return 'promoted'
  if (decision.promoted === false) return 'rejected'
  if (typeof decision.result === 'string') return (decision.result as string).toLowerCase()
  return undefined
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
      reason,
      result: gateResultText(decision),
    })
  }
  return gates
}

// ---------------------------------------------------------------------------
// Presentational primitives — no icons; the card is intentionally text-only.
// ---------------------------------------------------------------------------

function DimensionRow({ dim }: { dim: Dimension }) {
  return (
    <div className="grid grid-cols-12 gap-3 items-baseline px-6 py-2.5">
      <span className="col-span-3 text-sm font-medium text-foreground">{dim.name}</span>
      <span className="col-span-4 text-sm font-mono tabular-nums">{dim.headline}</span>
      <span className="col-span-5 text-xs text-muted-foreground">{dim.detail}</span>
      {dim.secondary && (
        <>
          <span className="col-span-3" />
          <span className="col-span-4 text-xs font-mono tabular-nums text-muted-foreground">
            {dim.secondary.label} {dim.secondary.value}
          </span>
          <span className="col-span-5 text-xs text-muted-foreground/80">
            {dim.secondary.detail}
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
        <span className="col-span-9 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          {gates.map((g) => (
            <span key={g.key} className="inline-flex items-center gap-1">
              <span className="font-medium text-foreground">{g.display}</span>
              {g.mode && (
                <span className="text-[11px] uppercase text-muted-foreground tracking-wide">
                  ({g.mode})
                </span>
              )}
              {g.result && (
                <span className="text-muted-foreground">— {g.result}</span>
              )}
            </span>
          ))}
        </span>
      </div>
      {gates
        .filter((g) => g.reason)
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
// Top-level card — text-only training diagnostics, no pass/fail verdicts.
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

  const trainingSamples = metrics.training_metadata?.train_size as number | undefined
  const segment = metrics.training_metadata?.segment as string | undefined
  const classBalance = metrics.training_metadata?.class_balance as number | undefined

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Training Diagnostics</CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          {trainingSamples != null
            ? `Trained on ${trainingSamples.toLocaleString()} synthetic samples`
            : 'Trained on (sample size unavailable)'}
          {segment ? ` · segment: ${segment}` : ''}
          {classBalance != null ? ` · ${(classBalance * 100).toFixed(1)}% positive rate` : ''}
        </p>
        <div className="mt-3 rounded-md border border-border bg-muted/30 px-3 py-2 flex items-start gap-2">
          <Info className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
          <p className="text-xs text-muted-foreground leading-snug">
            Values are reported on synthetic AU lending data calibrated against public sources
            (see backend/docs/CALIBRATION_SOURCES.md). Reference thresholds are shown for context;
            no pass/fail verdict is computed because the training distribution does not include
            real lender data.
          </p>
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
      </CardContent>
    </Card>
  )
}
