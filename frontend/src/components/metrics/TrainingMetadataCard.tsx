'use client'

import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, MinusCircle, XCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type Metadata = Record<string, unknown>

// Keys that pair with a sibling _mode key to describe a governance gate.
// Each one maps to a `<key>_mode` setting + a `<key>` decision object that
// the trainer (or ModelActivateView) wrote at activation time.
const GATE_KEYS = ['fairness_gate', 'promotion_gate', 'validation_gate'] as const

// Boolean flags that pair with the gates above — surfaced as warnings when set.
const REVIEW_FLAG_KEYS = [
  'requires_fairness_review',
  'requires_promotion_review',
  'validation_gate_blocked_demoted',
] as const

// Keys the trainer writes per `services/trainer.py` — listed explicitly so the
// "Training Run" section stays focused; anything not in this set falls into "Other".
const TRAINING_KEYS = new Set([
  'segment',
  'train_size',
  'val_size',
  'test_size',
  'class_balance',
  'training_time_seconds',
  'overfitting_gap',
  'train_auc',
  'n_features',
  'cv_auc_mean',
  'cv_auc_std',
  'cv_auc_per_fold',
  'cv_unstable',
  'cv_report',
  'temporal_cv_auc_mean',
  'temporal_cv_folds_used',
  'cv_drift_signal',
  'baseline_auc',
  'baseline_features',
  'xgb_lift_over_baseline',
  'optimal_threshold',
  'calibration_method',
  'group_thresholds',
  'iv_features_selected',
  'iv_features_excluded_weak',
  'iv_features_excluded_leakage',
])

function humanizeKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatScalar(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4)
  }
  return String(value)
}

function isPrimitiveArray(value: unknown): value is Array<string | number | boolean> {
  return (
    Array.isArray(value) &&
    value.every((v) => v === null || ['string', 'number', 'boolean'].includes(typeof v))
  )
}

function ModePill({ mode }: { mode: unknown }) {
  const m = String(mode).toLowerCase()
  const cls =
    m === 'block'
      ? 'bg-red-50 text-red-700 ring-red-200'
      : m === 'warn'
        ? 'bg-amber-50 text-amber-700 ring-amber-200'
        : 'bg-slate-50 text-slate-600 ring-slate-200'
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide ring-1 ring-inset ${cls}`}
    >
      mode: {m}
    </span>
  )
}

function BoolPill({ value }: { value: boolean }) {
  return value ? (
    <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset bg-emerald-50 text-emerald-700 ring-emerald-200">
      <CheckCircle2 className="h-3 w-3" /> Yes
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset bg-slate-50 text-slate-600 ring-slate-200">
      <XCircle className="h-3 w-3" /> No
    </span>
  )
}

function ResultPill({ result }: { result: string }) {
  if (result === 'passed') {
    return (
      <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset bg-emerald-50 text-emerald-700 ring-emerald-200">
        <CheckCircle2 className="h-3 w-3" /> Passed
      </span>
    )
  }
  if (result === 'blocked') {
    return (
      <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset bg-red-50 text-red-700 ring-red-200">
        <XCircle className="h-3 w-3" /> Blocked
      </span>
    )
  }
  if (result === 'skipped') {
    return (
      <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset bg-slate-50 text-slate-600 ring-slate-200">
        <MinusCircle className="h-3 w-3" /> Skipped
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset bg-amber-50 text-amber-700 ring-amber-200">
      <AlertTriangle className="h-3 w-3" /> Unknown
    </span>
  )
}

function gateResultFromDecision(decision: Record<string, unknown> | null): string {
  if (!decision) return 'unknown'
  if (typeof decision.result === 'string') return decision.result
  if (decision.passed === true) return 'passed'
  if (decision.passed === false) return 'blocked'
  if (decision.promoted === true) return 'passed'
  if (decision.promoted === false) return 'blocked'
  return 'unknown'
}

function GateRow({ name, mode, decision }: { name: string; mode?: unknown; decision: unknown }) {
  const decisionObj =
    decision && typeof decision === 'object' && !Array.isArray(decision)
      ? (decision as Record<string, unknown>)
      : null
  const result = gateResultFromDecision(decisionObj)

  // Pull the human-readable reason from whichever shape the gate uses.
  let reason: string | null = null
  if (decisionObj) {
    if (typeof decisionObj.reason === 'string') reason = decisionObj.reason
    else if (Array.isArray(decisionObj.reasons))
      reason = (decisionObj.reasons as unknown[]).filter((r) => typeof r === 'string').join('; ')
    else if (Array.isArray(decisionObj.failing_attributes) && decisionObj.failing_attributes.length > 0)
      reason = `Failing attributes: ${(decisionObj.failing_attributes as unknown[]).join(', ')}`
  }

  const [open, setOpen] = useState(false)

  return (
    <div className="px-6 py-3 space-y-1.5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <span className="text-sm font-medium text-foreground">{humanizeKey(name)}</span>
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          {mode != null && <ModePill mode={mode} />}
          <ResultPill result={result} />
        </div>
      </div>
      {reason && <div className="text-xs text-muted-foreground">{reason}</div>}
      {decisionObj && (
        <>
          <button
            type="button"
            onClick={() => setOpen((s) => !s)}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground/80 hover:text-foreground transition-colors"
          >
            <ChevronDown
              className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`}
            />
            {open ? 'Hide raw decision' : 'Show raw decision'}
          </button>
          {open && (
            <pre className="mt-1 rounded bg-muted/30 p-2.5 text-[11px] font-mono leading-relaxed overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(decisionObj, null, 2)}
            </pre>
          )}
        </>
      )}
    </div>
  )
}

function KvRow({ k, v }: { k: string; v: unknown }) {
  const [open, setOpen] = useState(false)

  // Render strategy: bools → pill; primitive arrays → inline list (with expand
  // when long); objects/non-primitive arrays → expandable JSON; long strings →
  // wrapped block; numbers/short strings → inline tabular value.
  if (typeof v === 'boolean') {
    return (
      <div className="grid grid-cols-2 gap-4 px-6 py-2.5">
        <span className="text-sm text-muted-foreground">{humanizeKey(k)}</span>
        <div className="text-right">
          <BoolPill value={v} />
        </div>
      </div>
    )
  }

  if (isPrimitiveArray(v)) {
    const items = v as Array<string | number | boolean>
    if (items.length === 0) {
      return (
        <div className="grid grid-cols-2 gap-4 px-6 py-2.5">
          <span className="text-sm text-muted-foreground">{humanizeKey(k)}</span>
          <span className="text-sm text-muted-foreground/60 text-right italic">empty</span>
        </div>
      )
    }
    const formatted = items.map((it) =>
      typeof it === 'number' ? (Number.isInteger(it) ? it.toString() : it.toFixed(3)) : String(it),
    )
    const inline = formatted.join(', ')
    const tooLong = inline.length > 80 || items.length > 8
    return (
      <div className="px-6 py-2.5">
        <div className="grid grid-cols-2 gap-4">
          <span className="text-sm text-muted-foreground">{humanizeKey(k)}</span>
          <div className="text-right">
            {tooLong ? (
              <button
                type="button"
                onClick={() => setOpen((s) => !s)}
                className="inline-flex items-center gap-1 text-xs text-foreground hover:underline"
              >
                <ChevronDown
                  className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`}
                />
                {items.length} values
              </button>
            ) : (
              <span className="text-sm font-mono tabular-nums break-words">[{inline}]</span>
            )}
          </div>
        </div>
        {tooLong && open && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {formatted.map((item, idx) => (
              <span
                key={idx}
                className="inline-flex items-center rounded bg-muted/40 px-1.5 py-0.5 text-[11px] font-mono"
              >
                {item}
              </span>
            ))}
          </div>
        )}
      </div>
    )
  }

  if (v !== null && typeof v === 'object') {
    const obj = v as Record<string, unknown>
    const summary = Array.isArray(v) ? `${v.length} items` : `${Object.keys(obj).length} fields`
    return (
      <div className="px-6 py-2.5 space-y-1.5">
        <div className="flex items-center justify-between gap-4">
          <span className="text-sm text-muted-foreground">{humanizeKey(k)}</span>
          <button
            type="button"
            onClick={() => setOpen((s) => !s)}
            className="inline-flex items-center gap-1 text-xs text-foreground hover:underline"
          >
            <ChevronDown className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`} />
            {summary}
          </button>
        </div>
        {open && (
          <pre className="rounded bg-muted/30 p-2.5 text-[11px] font-mono leading-relaxed overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(v, null, 2)}
          </pre>
        )}
      </div>
    )
  }

  if (typeof v === 'string' && v.length > 60) {
    return (
      <div className="px-6 py-2.5 space-y-1">
        <span className="text-sm text-muted-foreground">{humanizeKey(k)}</span>
        <p className="text-xs font-mono break-words text-foreground/90">{v}</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-4 px-6 py-2.5">
      <span className="text-sm text-muted-foreground">{humanizeKey(k)}</span>
      <span
        className="text-sm font-mono text-right tabular-nums break-words"
        title={String(v)}
      >
        {formatScalar(v)}
      </span>
    </div>
  )
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80 bg-muted/20">
      {children}
    </div>
  )
}

interface TrainingMetadataCardProps {
  metadata: Metadata
  optimalThreshold?: number | null
}

export function TrainingMetadataCard({ metadata, optimalThreshold }: TrainingMetadataCardProps) {
  if (!metadata || Object.keys(metadata).length === 0) return null

  const consumedKeys = new Set<string>()
  const gates: Array<{ name: string; mode?: unknown; decision: unknown }> = []
  for (const gateKey of GATE_KEYS) {
    const modeKey = `${gateKey}_mode`
    const hasGate = gateKey in metadata
    const hasMode = modeKey in metadata
    if (hasGate || hasMode) {
      gates.push({
        name: gateKey,
        mode: metadata[modeKey],
        decision: metadata[gateKey],
      })
      if (hasGate) consumedKeys.add(gateKey)
      if (hasMode) consumedKeys.add(modeKey)
    }
  }

  const activeReviewFlags: string[] = []
  for (const flagKey of REVIEW_FLAG_KEYS) {
    if (flagKey in metadata) {
      consumedKeys.add(flagKey)
      if (metadata[flagKey] === true) activeReviewFlags.push(flagKey)
    }
  }

  const trainingEntries: Array<[string, unknown]> = []
  const otherEntries: Array<[string, unknown]> = []
  for (const [k, v] of Object.entries(metadata)) {
    if (consumedKeys.has(k)) continue
    if (TRAINING_KEYS.has(k)) trainingEntries.push([k, v])
    else otherEntries.push([k, v])
  }

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Training Metadata</CardTitle>
      </CardHeader>
      <CardContent className="px-0 space-y-0">
        {gates.length > 0 && (
          <section className="divide-y divide-border">
            <SectionHeader>Governance Gates</SectionHeader>
            {gates.map((g) => (
              <GateRow key={g.name} {...g} />
            ))}
            {activeReviewFlags.length > 0 && (
              <div className="px-6 py-3 space-y-1 bg-amber-50/40">
                {activeReviewFlags.map((k) => (
                  <div key={k} className="flex items-center gap-2 text-xs text-amber-800">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                    <span>{humanizeKey(k)}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {trainingEntries.length > 0 && (
          <section className="divide-y divide-border border-t border-border">
            <SectionHeader>Training Run</SectionHeader>
            {trainingEntries.map(([k, v]) => (
              <KvRow key={k} k={k} v={v} />
            ))}
            {optimalThreshold != null && (
              <div className="grid grid-cols-2 gap-4 px-6 py-2.5 bg-muted/30">
                <span className="text-sm font-medium text-muted-foreground">Active Threshold</span>
                <span className="text-sm font-mono font-semibold text-right tabular-nums">
                  {optimalThreshold.toFixed(2)}
                </span>
              </div>
            )}
          </section>
        )}

        {otherEntries.length > 0 && (
          <section className="divide-y divide-border border-t border-border">
            <SectionHeader>Other</SectionHeader>
            {otherEntries.map(([k, v]) => (
              <KvRow key={k} k={k} v={v} />
            ))}
          </section>
        )}
      </CardContent>
    </Card>
  )
}
