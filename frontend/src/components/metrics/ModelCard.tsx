'use client'

import { useState } from 'react'
import { ChevronDown, Info } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import {
  AUC_REGULATOR_FLOOR,
  KS_REGULATOR_FLOOR,
  ECE_CEILING,
  GAP_CEILING,
  GMSC_AUC,
  GMSC_DATASET_LABEL,
  GMSC_REFERENCE_URL,
  AU_CALIBRATION_SOURCES,
  CALIBRATION_SOURCES_URL,
  NOT_VALIDATED_FOR,
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

// Reference thresholds are shown next to each metric for context, but the
// rendered copy is intentionally neutral — no "above/below" language and no
// pass/fail icons — because the underlying training data is synthetic and a
// hard verdict against industry floors would overclaim real-world performance.
function aucContext(auc: number | null | undefined): string {
  if (auc == null) return 'AUC not recorded'
  return `regulator floor: ${AUC_REGULATOR_FLOOR.toFixed(2)}`
}

function ksContext(ks: number | null | undefined): string {
  if (ks == null) return 'KS not recorded'
  return `regulator floor: ${KS_REGULATOR_FLOOR.toFixed(2)}`
}

function eceContext(ece: number | null | undefined): string {
  if (ece == null) return 'ECE not recorded'
  return `industry ceiling: ${ECE_CEILING.toFixed(2)}`
}

function gapContext(gap: number | null | undefined): string {
  if (gap == null) return 'gap not recorded'
  return `industry ceiling: ${GAP_CEILING.toFixed(2)}`
}

// ---------------------------------------------------------------------------
// Confusion matrix row — folds the legacy ConfusionMatrix card into a single
// text line. Senior reviewers and lending analysts read precision/recall/n,
// not a 2×2 grid.
// ---------------------------------------------------------------------------

function readConfusion(
  cm: ModelMetrics['confusion_matrix'] | null | undefined,
): { p: number; r: number; n: number } | null {
  if (!cm) return null
  const tp = cm.tp ?? cm.true_positives ?? 0
  const fp = cm.fp ?? cm.false_positives ?? 0
  const tn = cm.tn ?? cm.true_negatives ?? 0
  const fn = cm.fn ?? cm.false_negatives ?? 0
  const n = tp + fp + tn + fn
  if (n === 0) return null
  const p = tp + fp > 0 ? tp / (tp + fp) : 0
  const r = tp + fn > 0 ? tp / (tp + fn) : 0
  return { p, r, n }
}

// ---------------------------------------------------------------------------
// Credibility section — top-3 drivers normalised from either feature
// importance shape (object map or array). The point is to show a senior
// reviewer the model relies on plausible economic features, not noise.
// ---------------------------------------------------------------------------

interface DriverRow {
  feature: string
  importance: number
}

function topDrivers(
  fi: ModelMetrics['feature_importances'],
  limit = 3,
): DriverRow[] {
  if (!fi) return []
  let rows: DriverRow[]
  if (Array.isArray(fi)) {
    rows = fi
      .filter(
        (r): r is { feature: string; importance: number } =>
          typeof r?.feature === 'string' && typeof r?.importance === 'number',
      )
      .map((r) => ({ feature: r.feature, importance: r.importance }))
  } else {
    rows = Object.entries(fi)
      .filter((entry): entry is [string, number] => typeof entry[1] === 'number')
      .map(([feature, importance]) => ({ feature, importance }))
  }
  return rows.sort((a, b) => b.importance - a.importance).slice(0, limit)
}

function hasMoreFeatures(
  fi: ModelMetrics['feature_importances'],
  topShown: number,
): boolean {
  if (!fi) return false
  if (Array.isArray(fi)) return fi.length > topShown
  return Object.keys(fi).length > topShown
}

function CredibilitySection({ metrics }: { metrics: ModelMetrics }) {
  const drivers = topDrivers(metrics.feature_importances, 3)
  const [showAll, setShowAll] = useState(false)
  const moreAvailable = hasMoreFeatures(metrics.feature_importances, 3)

  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
        Credibility evidence
      </h4>
      <div className="space-y-2 rounded-md border border-slate-100 bg-slate-50/40 p-4">
        <p className="text-xs text-muted-foreground">
          Top drivers — the features the model leans on most for its decision.
        </p>
        {drivers.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No feature-importance data recorded for this model.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {drivers.map((d, idx) => (
              <li
                key={d.feature}
                className="flex items-baseline justify-between gap-3 text-sm"
              >
                <span className="flex items-baseline gap-2">
                  <span className="text-xs font-medium text-slate-400 tabular-nums">
                    {idx + 1}.
                  </span>
                  <span className="font-mono text-slate-700">{d.feature}</span>
                </span>
                <span className="font-mono tabular-nums text-slate-900">
                  {d.importance.toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {moreAvailable && (
          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowAll((s) => !s)}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:text-blue-800 transition-colors"
              aria-expanded={showAll}
            >
              <ChevronDown
                className={`h-3.5 w-3.5 transition-transform ${showAll ? 'rotate-180' : ''}`}
              />
              {showAll ? 'Hide full feature ranking' : 'Show all features'}
            </button>
            {showAll && (
              <div className="mt-3">
                <FeatureImportance
                  features={metrics.feature_importances}
                  title="All features by importance"
                />
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Trained-On section — anchors the calibration claim. Lists the short names
// of the AU public statistical sources DataGenerator calibrates against, with
// a single "View calibration sources" link to the manifest in the repo. The
// link points at master so a CV/portfolio reader can audit the evidence
// without logging in.
// ---------------------------------------------------------------------------

function TrainedOnSection() {
  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
        Trained on
      </h4>
      <div className="space-y-3 rounded-md border border-slate-100 bg-slate-50/40 p-4">
        <p className="text-xs text-muted-foreground">
          Synthetic Australian retail-lending data calibrated against public
          regulator and statistical-agency releases:
        </p>
        <ul className="flex flex-wrap gap-2">
          {AU_CALIBRATION_SOURCES.map((source) => (
            <li key={source.short}>
              <span
                className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-xs font-medium text-slate-700"
                title={source.full}
              >
                {source.short}
              </span>
            </li>
          ))}
        </ul>
        <a
          className="inline-block text-xs font-medium text-blue-600 underline decoration-dotted underline-offset-2 hover:text-blue-800"
          href={CALIBRATION_SOURCES_URL}
          target="_blank"
          rel="noreferrer noopener"
        >
          View calibration sources →
        </a>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Not-Validated-For section — explicit out-of-scope statement. Mirrors the
// "intended_use.out_of_scope" section in the canonical model card and the
// risk register. The point is honesty: a portfolio reader should be able to
// see at-a-glance which populations the project owner does NOT claim to
// have validated against.
// ---------------------------------------------------------------------------

function NotValidatedForSection() {
  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
        Not validated for
      </h4>
      <div className="rounded-md border border-amber-200 bg-amber-50/40 p-4">
        <ul className="space-y-1 text-sm text-slate-700">
          {NOT_VALIDATED_FOR.map((item) => (
            <li key={item} className="flex gap-2">
              <span className="text-amber-600" aria-hidden>
                ·
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Production posture section — explicit Active/Retired badge plus a one-line
// statement of what that means in user-facing terms. Anchors the rest of the
// card to a current operational state — a good model card without this is
// just a sales sheet.
// ---------------------------------------------------------------------------

function ProductionPostureSection({ metrics }: { metrics: ModelMetrics }) {
  const active = metrics.is_active === true
  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
        Production posture
      </h4>
      <div className="flex items-start gap-3 rounded-md border border-slate-100 bg-slate-50/40 p-4">
        {active ? (
          <span className="inline-flex shrink-0 items-center rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
            Active
          </span>
        ) : (
          <span className="inline-flex shrink-0 items-center rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
            Retired
          </span>
        )}
        <p className="text-sm text-slate-700">
          {active
            ? 'Serving live predictions on /dashboard/applications. Decisions made by this model are persisted to LoanDecision rows with full audit context.'
            : 'Not currently serving predictions. This card is shown for historical reference only.'}
        </p>
      </div>
    </section>
  )
}

function PerformanceSection({ metrics }: { metrics: ModelMetrics }) {
  const auc = metrics.auc_roc ?? null
  const ks = metrics.ks_statistic ?? null
  const ece = metrics.calibration_data?.ece ?? metrics.ece ?? null
  const gini = metrics.gini_coefficient ?? null
  const brier = metrics.brier_score ?? null
  const gap = (metrics.training_metadata?.overfitting_gap as number | undefined) ?? null
  const lift = (metrics.training_metadata?.xgb_lift_over_baseline as
    | number
    | undefined) ?? null
  const baselineAuc = (metrics.training_metadata?.baseline_auc as
    | number
    | undefined) ?? null
  const confusion = readConfusion(metrics.confusion_matrix)

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
        {gini != null && (
          <MetricRow
            label="Gini"
            value={gini.toFixed(3)}
            context="industry floor: 0.40"
          />
        )}
        <MetricRow
          label="ECE (calibration error)"
          value={ece != null ? ece.toFixed(4) : '—'}
          context={eceContext(ece)}
        />
        {brier != null && (
          <MetricRow
            label="Brier score"
            value={brier.toFixed(4)}
            context="lower is better"
          />
        )}
        {gap != null && (
          <MetricRow
            label="Train→test gap"
            value={gap.toFixed(3)}
            context={gapContext(gap)}
          />
        )}
        {lift != null && baselineAuc != null && (
          <MetricRow
            label="Lift over LR"
            value={`${lift >= 0 ? '+' : ''}${lift.toFixed(3)} AUC`}
            context={`vs LR baseline AUC ${baselineAuc.toFixed(3)}`}
          />
        )}
        {confusion && (
          <MetricRow
            label="Confusion"
            value={`P ${confusion.p.toFixed(2)} · R ${confusion.r.toFixed(2)}`}
            context={`n = ${confusion.n.toLocaleString()}`}
          />
        )}
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

// ---------------------------------------------------------------------------
// Decision thresholds row — folds ThresholdChart's three optimal-cutoff badges
// into a single one-liner. The threshold sweep visual is gone; analysts read
// the chosen cutoffs as numbers, not as a four-line trade-off plot.
// ---------------------------------------------------------------------------

function DecisionThresholdsSection({ metrics }: { metrics: ModelMetrics }) {
  const active = metrics.optimal_threshold ?? null
  const ta = metrics.threshold_analysis ?? null
  const f1Opt = ta?.f1_optimal_threshold ?? null
  const youden = ta?.youden_j_threshold ?? null
  const costOpt = ta?.cost_optimal_threshold ?? null

  if (active == null && f1Opt == null && youden == null && costOpt == null) {
    return null
  }

  const fmt = (v: number | null) => (v != null ? v.toFixed(2) : '—')

  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
        Decision thresholds
      </h4>
      <div className="rounded-md border border-slate-100 bg-slate-50/40 p-4 text-sm text-slate-700">
        <span className="font-medium">Active</span>{' '}
        <span className="font-mono tabular-nums text-slate-900">{fmt(active)}</span>
        {f1Opt != null && (
          <>
            <span className="text-slate-400"> · </span>
            F1-optimal{' '}
            <span className="font-mono tabular-nums text-slate-900">
              {fmt(f1Opt)}
            </span>
          </>
        )}
        {youden != null && (
          <>
            <span className="text-slate-400"> · </span>
            Youden{"'"}s J{' '}
            <span className="font-mono tabular-nums text-slate-900">
              {fmt(youden)}
            </span>
          </>
        )}
        {costOpt != null && (
          <>
            <span className="text-slate-400"> · </span>
            Cost-optimal{' '}
            <span className="font-mono tabular-nums text-slate-900">
              {fmt(costOpt)}
            </span>
          </>
        )}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Empty-state banner — fires when the active ModelVersion was trained against
// an older pipeline that never produced AUC, calibration data, or feature
// importances. The Card still renders the surrounding sections honestly
// ("AUC not recorded", "no feature-importance data") but the banner up-top
// turns the cumulative absence into a single actionable message instead of
// leaving the reader to piece it together row by row.
// ---------------------------------------------------------------------------

function hasEvidence(metrics: ModelMetrics): boolean {
  if (metrics.auc_roc != null) return true
  const ece = metrics.calibration_data?.ece ?? metrics.ece
  if (ece != null) return true
  const fi = metrics.feature_importances
  if (Array.isArray(fi)) return fi.length > 0
  if (fi && typeof fi === 'object') return Object.keys(fi).length > 0
  return false
}

function EmptyStateBanner() {
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <p className="font-semibold">Limited evidence available</p>
      <p className="mt-1 text-amber-800">
        This model was trained against an older pipeline that did not record
        the metrics this card surfaces. Re-train against the latest trainer
        (run "Train New Model" above) to populate AUC, calibration error, and
        feature importances.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Raw metadata footer — lifted verbatim from the legacy ModelHealthCard so
// the same KV escape hatch survives the consolidation. Power users (risk
// reviewers, ML engineers auditing a run) keep one collapsible KV view of the
// full training_metadata JSON without leaving the page.
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

function RawMetadataFooter({
  metadata,
  optimalThreshold,
}: {
  metadata: Record<string, unknown> | null | undefined
  optimalThreshold: number | null | undefined
}) {
  const [open, setOpen] = useState(false)
  const entries = metadata ? Object.entries(metadata) : []
  if (entries.length === 0 && optimalThreshold == null) return null

  return (
    <div className="border-t border-slate-200 pt-4">
      <button
        type="button"
        onClick={() => setOpen((s) => !s)}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
        aria-expanded={open}
      >
        <ChevronDown
          className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-180' : ''}`}
        />
        {open ? 'Hide raw training metadata' : 'Show raw training metadata'}
      </button>
      {open && (
        <div className="mt-3 rounded-md border border-border overflow-hidden">
          <div className="divide-y divide-border bg-muted/10">
            {entries.map(([key, value]) => (
              <div key={key} className="grid grid-cols-2 gap-4 px-4 py-2">
                <span className="text-xs text-muted-foreground">
                  {humanizeKey(key)}
                </span>
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
                <span className="text-xs font-medium text-foreground">
                  Active threshold
                </span>
                <span className="text-xs font-mono font-semibold text-right tabular-nums">
                  {optimalThreshold.toFixed(2)}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
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
  const evidence = hasEvidence(metrics)

  return (
    <Card>
      <CardHeader className="space-y-1">
        <CardTitle>Model Card</CardTitle>
        <p className="text-sm text-muted-foreground">
          {algorithm} <span className="text-slate-400">·</span> v{version}{' '}
          <span className="text-slate-400">·</span> {segment}
        </p>
        <div className="mt-2 flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50/60 px-3 py-2">
          <Info className="h-3.5 w-3.5 mt-0.5 shrink-0 text-slate-500" />
          <p className="text-xs text-slate-600 leading-snug">
            Trained on synthetic Australian retail-lending data calibrated against
            public regulator and statistical-agency releases. Reference thresholds
            are shown for context; numbers should not be read as a real-world
            performance claim.
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {!evidence && <EmptyStateBanner />}
        <PerformanceSection metrics={metrics} />
        <DecisionThresholdsSection metrics={metrics} />
        <CredibilitySection metrics={metrics} />
        <TrainedOnSection />
        <NotValidatedForSection />
        <ProductionPostureSection metrics={metrics} />
        <RawMetadataFooter
          metadata={metrics.training_metadata}
          optimalThreshold={metrics.optimal_threshold}
        />
      </CardContent>
    </Card>
  )
}
