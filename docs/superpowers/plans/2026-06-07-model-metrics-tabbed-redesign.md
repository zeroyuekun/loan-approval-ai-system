# Model Metrics Tabbed Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganise the Model Metrics dashboard into a tabbed, progressively-disclosed layout, decompose the 357-line page into focused components, and fix small viz/numeric correctness nits — with no API/data changes and existing tests kept green.

**Architecture:** A thin page orchestrator renders an always-visible model header + 5-metric KPI strip, then a `Tabs` shell (Performance / Fairness / Calibration & Thresholds / Drift / Diagnostics). Existing chart components are reused, regrouped into per-tab wrapper components. Two redundant drift cards merge into one `DriftPanel`. Backend ECE becomes population-weighted.

**Tech Stack:** Next.js (App Router, `src/`), React, TypeScript, recharts, custom `ui/tabs.tsx` (context-based, unmounts inactive tabs), Tailwind/shadcn-style components, vitest + Testing Library + MSW (frontend); Django + pytest, numpy/sklearn (backend).

---

## File Structure

**Create (frontend):**
- `src/components/metrics/TrainControl.tsx` — algorithm `Select` + train `Button` (reused by header and no-model state).
- `src/components/metrics/ModelHeader.tsx` — title, version/Active badges, admin TrainControl, and the 4 training state banners.
- `src/components/metrics/KpiStrip.tsx` — 5 classic metrics, AUC-ROC as hero.
- `src/components/metrics/DriftPanel.tsx` — merged drift card (status + headline PSI + 4 stats + PSI-over-time trend). Replaces `DriftOverview` + `DriftPsiChart`.
- `src/components/metrics/diagnostics.ts` — curated-metadata helper.
- `src/components/metrics/tabs/PerformanceTab.tsx`
- `src/components/metrics/tabs/FairnessTab.tsx`
- `src/components/metrics/tabs/CalibrationThresholdsTab.tsx`
- `src/components/metrics/tabs/DriftTab.tsx`
- `src/components/metrics/tabs/DiagnosticsTab.tsx`

**Modify (frontend):**
- `src/app/dashboard/model-metrics/page.tsx` — becomes orchestrator.
- `src/components/metrics/FeatureImportance.tsx` — cap to top 15.
- `src/components/metrics/CalibrationChart.tsx` — straight segments (drop `monotone`).
- `src/components/metrics/ConfusionMatrix.tsx` — normalise cell colour.
- `src/__tests__/pages/ModelMetricsPage.test.tsx` — add tab-switching tests.

**Delete (frontend, after migration):**
- `src/components/metrics/DriftOverview.tsx`
- `src/components/metrics/DriftPsiChart.tsx`

**Modify (backend):**
- `backend/apps/ml_engine/services/metrics.py` — population-weighted ECE in `compute_calibration_data`; remove dead `y_prob[order]` line in `compute_decile_analysis`.
- `backend/apps/ml_engine/tests/test_metrics_production_grade.py` — add weighted-ECE test.

**Create (frontend tests):**
- `src/__tests__/components/metrics/KpiStrip.test.tsx`
- `src/__tests__/components/metrics/DriftPanel.test.tsx`
- `src/__tests__/components/metrics/diagnostics.test.ts`
- `src/__tests__/components/metrics/FeatureImportance.test.tsx`

**Conventions:** Run frontend commands from `frontend/`. Frontend tests: `npx vitest run <path>`. Typecheck: `npx tsc --noEmit`. Backend tests run in the container: `docker exec loan-approval-ai-system-backend-1 python -m pytest <path> -v`. Commit after each task.

---

## Task 1: Backend — population-weighted ECE + dead-line removal

**Files:**
- Modify: `backend/apps/ml_engine/services/metrics.py` (`compute_calibration_data` ~lines 97-109; `compute_decile_analysis` line 172; top import line 12)
- Test: `backend/apps/ml_engine/tests/test_metrics_production_grade.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/ml_engine/tests/test_metrics_production_grade.py`:

```python
import numpy as np
from apps.ml_engine.services.metrics import MetricsService


def test_ece_is_population_weighted():
    """ECE must weight each bin by its sample count, not average bins equally.

    90 samples at p=0.05 (10% positive -> gap 0.05) and 10 samples at p=0.85
    (50% positive -> gap 0.35). Unweighted mean of gaps = 0.20; population-
    weighted ECE = 0.9*0.05 + 0.1*0.35 = 0.08.
    """
    svc = MetricsService()
    y_prob = np.concatenate([np.full(90, 0.05), np.full(10, 0.85)])
    y_true = np.concatenate([
        np.array([1] * 9 + [0] * 81),   # 9/90 positive in low bin
        np.array([1] * 5 + [0] * 5),     # 5/10 positive in high bin
    ])

    result = svc.compute_calibration_data(y_true, y_prob, n_bins=10)

    assert result["ece"] == 0.08
    # Two non-empty bins, points consistent with the binning
    assert result["mean_predicted_value"] == [0.05, 0.85]
    assert result["fraction_of_positives"] == [0.1, 0.5]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec loan-approval-ai-system-backend-1 python -m pytest apps/ml_engine/tests/test_metrics_production_grade.py::test_ece_is_population_weighted -v`
Expected: FAIL — current ECE ≈ 0.20 (unweighted), not 0.08.

- [ ] **Step 3: Reimplement `compute_calibration_data` with manual uniform binning**

Replace the whole method (`metrics.py` ~lines 97-109):

```python
    def compute_calibration_data(self, y_true, y_prob, n_bins=10):
        """Reliability-diagram data with a population-WEIGHTED ECE.

        ECE = sum_k (n_k / N) * |fraction_positive_k - mean_predicted_k| over
        non-empty uniform bins, so sparsely populated bins do not dominate.
        """
        y_true = np.asarray(y_true, dtype=float)
        y_prob = np.asarray(y_prob, dtype=float)
        n = len(y_true)

        edges = np.linspace(0.0, 1.0, n_bins + 1)
        bin_ids = np.clip(np.digitize(y_prob, edges[1:-1]), 0, n_bins - 1)

        fraction_of_positives = []
        mean_predicted_value = []
        ece = 0.0
        for i in range(n_bins):
            mask = bin_ids == i
            count = int(mask.sum())
            if count == 0:
                continue
            frac_pos = float(y_true[mask].mean())
            mean_pred = float(y_prob[mask].mean())
            fraction_of_positives.append(round(frac_pos, 4))
            mean_predicted_value.append(round(mean_pred, 4))
            ece += (count / n) * abs(frac_pos - mean_pred)

        return {
            "fraction_of_positives": fraction_of_positives,
            "mean_predicted_value": mean_predicted_value,
            "ece": round(float(ece), 4),
            "n_bins": n_bins,
        }
```

- [ ] **Step 4: Remove the now-unused sklearn import and the dead decile line**

In `metrics.py`, delete `calibration_curve` from the import block (line 12 region): change
`from sklearn.calibration import calibration_curve` — remove that line entirely (it has no other
caller after Step 3; confirm with `grep -n calibration_curve metrics.py` → no remaining hits).

In `compute_decile_analysis`, delete the dead line that computes but discards a value (line ~172):

```python
        y_true_sorted = y_true[order]
        y_prob[order]          # <-- DELETE this line (computed and thrown away)
```

so it becomes:

```python
        y_true_sorted = y_true[order]
```

- [ ] **Step 5: Run the new test + the existing metrics suite**

Run: `docker exec loan-approval-ai-system-backend-1 python -m pytest apps/ml_engine/tests/test_metrics_production_grade.py -v`
Expected: PASS (new test + all existing). Then sanity-check nothing else imported `calibration_curve`:
Run: `docker exec loan-approval-ai-system-backend-1 grep -rn calibration_curve apps/ml_engine`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/ml_engine/services/metrics.py backend/apps/ml_engine/tests/test_metrics_production_grade.py
git commit -m "fix(ml): population-weighted ECE + drop dead decile line"
```

---

## Task 2: FeatureImportance — cap to top 15

**Files:**
- Modify: `frontend/src/components/metrics/FeatureImportance.tsx:116-153`
- Test: `frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

function makeFeatures(n: number): Record<string, number> {
  const out: Record<string, number> = {}
  for (let i = 0; i < n; i++) out[`feature_${i}`] = (n - i) / n
  return out
}

describe('FeatureImportance', () => {
  it('caps to the top 15 features and notes how many are hidden', () => {
    render(<FeatureImportance features={makeFeatures(20)} />)
    // Highest-importance feature shown, 16th-ranked one not shown
    expect(screen.getByText('Feature 0')).toBeInTheDocument()
    expect(screen.queryByText('Feature 15')).not.toBeInTheDocument()
    expect(screen.getByText(/\+5 more/i)).toBeInTheDocument()
  })

  it('shows no "+N more" note when 15 or fewer features', () => {
    render(<FeatureImportance features={makeFeatures(10)} />)
    expect(screen.queryByText(/more/i)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/components/metrics/FeatureImportance.test.tsx`
Expected: FAIL — currently renders all 20 (`Feature 15` present, no "+N more").

- [ ] **Step 3: Add the top-15 cap**

In `FeatureImportance.tsx`, after the existing `const data = (...).filter(...).sort(...)` block (ends line ~128), insert:

```tsx
  const TOP_N = 15
  const hiddenCount = Math.max(0, data.length - TOP_N)
  const shown = data.slice(0, TOP_N)
```

Then change the chart to use `shown` instead of `data`:
- `aria-label`: use `shown.length` and `shown.slice(0, 3)`.
- `ResponsiveContainer height={Math.max(280, shown.length * 36)}`.
- `<BarChart data={shown} ...>`.

And add a footer note inside `<CardContent>`, after the `</ResponsiveContainer>`'s wrapping `</div>`:

```tsx
        {hiddenCount > 0 && (
          <p className="mt-2 text-center text-xs text-muted-foreground">
            +{hiddenCount} more feature{hiddenCount === 1 ? '' : 's'} not shown
          </p>
        )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/components/metrics/FeatureImportance.test.tsx`
Expected: PASS (both cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/metrics/FeatureImportance.tsx frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx
git commit -m "feat(metrics): cap feature importance to top 15"
```

---

## Task 3: CalibrationChart straight-line + ConfusionMatrix colour

These are visual-correctness fixes; recharts SVG internals are not meaningfully assertable in jsdom, so verify by typecheck + the page test suite (Task 9) and a manual look.

**Files:**
- Modify: `frontend/src/components/metrics/CalibrationChart.tsx:52-58`
- Modify: `frontend/src/components/metrics/ConfusionMatrix.tsx:19-28`

- [ ] **Step 1: Calibration — use straight segments**

In `CalibrationChart.tsx`, change the `<Line>` `type` from `monotone` to `linear` so the reliability
diagram is not splined:

```tsx
            <Line
              type="linear"
              dataKey="actual"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={{ r: 4 }}
              name="Actual"
            />
```

- [ ] **Step 2: Confusion matrix — normalise colour to the off-diagonal scale**

In `ConfusionMatrix.tsx`, replace the intensity scaling so the (typically huge) TN cell no longer
flattens the others. Replace lines ~19-28:

```tsx
  const total = matrix.tp + matrix.fp + matrix.tn + matrix.fn
  // Scale colour to the largest of the four cells INDEPENDENTLY of TN, which on
  // imbalanced data dwarfs the rest and washes the heat-map out. TN keeps a
  // fixed light tint; the other three scale against their own max.
  const offDiagMax = Math.max(matrix.tp, matrix.fp, matrix.fn)

  function getIntensity(value: number, isTrueNegative = false): string {
    if (isTrueNegative) return 'bg-blue-100 text-blue-900'
    const ratio = offDiagMax > 0 ? value / offDiagMax : 0
    if (ratio > 0.75) return 'bg-blue-600 text-white'
    if (ratio > 0.5) return 'bg-blue-400 text-white'
    if (ratio > 0.25) return 'bg-blue-200 text-blue-900'
    return 'bg-blue-50 text-blue-900'
  }
```

Then update the TN cell call (line ~66) to pass the flag:

```tsx
            <div className={`flex h-24 w-24 items-center justify-center rounded-md text-lg font-bold ${getIntensity(matrix.tn, true)}`}>
```

(The TP/FP/FN cells keep `getIntensity(matrix.tp)` etc.)

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/metrics/CalibrationChart.tsx frontend/src/components/metrics/ConfusionMatrix.tsx
git commit -m "fix(metrics): straight calibration line + balanced confusion-matrix colour"
```

---

## Task 4: KpiStrip component (AUC hero)

**Files:**
- Create: `frontend/src/components/metrics/KpiStrip.tsx`
- Test: `frontend/src/__tests__/components/metrics/KpiStrip.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/components/metrics/KpiStrip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { KpiStrip } from '@/components/metrics/KpiStrip'

describe('KpiStrip', () => {
  const metrics = { accuracy: 0.811, precision: 0.886, recall: 0.765, f1_score: 0.821, auc_roc: 0.871 }

  it('renders all five classic metric labels', () => {
    render(<KpiStrip metrics={metrics} />)
    for (const label of ['AUC-ROC', 'Accuracy', 'Precision', 'Recall', 'F1 Score']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows AUC as a 3-decimal hero value and rates as percentages', () => {
    render(<KpiStrip metrics={metrics} />)
    expect(screen.getByText('0.871')).toBeInTheDocument()   // AUC hero
    expect(screen.getByText('81.1%')).toBeInTheDocument()   // accuracy
  })

  it('renders an em dash for null values', () => {
    render(<KpiStrip metrics={{ accuracy: null, precision: null, recall: null, f1_score: null, auc_roc: null }} />)
    expect(screen.getAllByText('—').length).toBe(5)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/components/metrics/KpiStrip.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement KpiStrip**

Create `frontend/src/components/metrics/KpiStrip.tsx`:

```tsx
'use client'

import { Card, CardContent } from '@/components/ui/card'
import { formatPercent } from '@/lib/utils'
import { ModelMetrics } from '@/types'

type KpiStripProps = {
  metrics: Pick<ModelMetrics, 'accuracy' | 'precision' | 'recall' | 'f1_score' | 'auc_roc'>
}

export function KpiStrip({ metrics }: KpiStripProps) {
  const secondary = [
    { label: 'Accuracy', value: metrics.accuracy },
    { label: 'Precision', value: metrics.precision },
    { label: 'Recall', value: metrics.recall },
    { label: 'F1 Score', value: metrics.f1_score },
  ]

  return (
    <div className="grid gap-4 grid-cols-2 lg:grid-cols-5">
      <Card className="col-span-2 border-primary/30 bg-primary/5 lg:col-span-1">
        <CardContent className="pt-5 pb-4">
          <p className="mb-1.5 text-xs font-medium text-primary/80">AUC-ROC</p>
          <p className="text-3xl font-bold tabular-nums text-primary">
            {metrics.auc_roc != null ? metrics.auc_roc.toFixed(3) : '—'}
          </p>
        </CardContent>
      </Card>
      {secondary.map((m) => (
        <Card key={m.label}>
          <CardContent className="pt-5 pb-4">
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">{m.label}</p>
            <p className="text-2xl font-bold tabular-nums">
              {m.value != null ? formatPercent(m.value) : '—'}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/components/metrics/KpiStrip.test.tsx`
Expected: PASS (all three cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/metrics/KpiStrip.tsx frontend/src/__tests__/components/metrics/KpiStrip.test.tsx
git commit -m "feat(metrics): KpiStrip component with AUC hero"
```

---

## Task 5: DriftPanel (merge DriftOverview + DriftPsiChart)

**Files:**
- Create: `frontend/src/components/metrics/DriftPanel.tsx`
- Test: `frontend/src/__tests__/components/metrics/DriftPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/components/metrics/DriftPanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { DriftPanel } from '@/components/metrics/DriftPanel'
import { DriftReport } from '@/types'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

const reports: DriftReport[] = [
  {
    id: 'r2', report_date: '2026-06-01', psi_score: 0.07, psi_per_feature: {},
    mean_probability: 0.42, std_probability: 0.2, approval_rate: 0.55,
    drift_detected: false, alert_level: 'none', num_predictions: 1200,
    period_start: '2026-05-01', period_end: '2026-06-01',
  },
  {
    id: 'r1', report_date: '2026-05-01', psi_score: 0.03, psi_per_feature: {},
    mean_probability: 0.4, std_probability: 0.2, approval_rate: 0.5,
    drift_detected: false, alert_level: 'none', num_predictions: 1000,
    period_start: '2026-04-01', period_end: '2026-05-01',
  },
]

describe('DriftPanel', () => {
  it('shows the latest PSI, status, and prediction count', () => {
    render(<DriftPanel reports={reports} />)
    expect(screen.getByText('0.0700')).toBeInTheDocument()      // latest psi (reports[0])
    expect(screen.getByText('Stable')).toBeInTheDocument()       // alert_level none
    expect(screen.getByText('1,200')).toBeInTheDocument()        // num_predictions
  })

  it('renders nothing when there are no reports', () => {
    const { container } = render(<DriftPanel reports={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/components/metrics/DriftPanel.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement DriftPanel**

Create `frontend/src/components/metrics/DriftPanel.tsx`:

```tsx
'use client'

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Label } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { DriftReport } from '@/types'

interface DriftPanelProps {
  reports: DriftReport[]
}

const ALERT_CONFIG: Record<string, { label: string; variant: 'success' | 'warning' | 'destructive' }> = {
  none: { label: 'Stable', variant: 'success' },
  moderate: { label: 'Investigate', variant: 'warning' },
  significant: { label: 'Action Required', variant: 'destructive' },
}

export function DriftPanel({ reports }: DriftPanelProps) {
  if (!reports.length) return null

  const latest = reports[0]
  const config = ALERT_CONFIG[latest.alert_level] || ALERT_CONFIG.none
  const trend = [...reports].reverse().map((r) => ({
    date: r.report_date,
    psi: parseFloat((r.psi_score ?? 0).toFixed(4)),
  }))

  const stats = [
    { label: 'Report Date', value: latest.report_date },
    { label: 'Predictions', value: latest.num_predictions.toLocaleString() },
    { label: 'Approval Rate', value: latest.approval_rate != null ? `${(latest.approval_rate * 100).toFixed(1)}%` : '—' },
    { label: 'Mean Probability', value: latest.mean_probability != null ? latest.mean_probability.toFixed(4) : '—' },
  ]

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Data Drift (PSI)</CardTitle>
          <Badge variant={config.variant}>{config.label}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-4">
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Latest PSI Score</p>
              <p className="text-3xl font-bold tabular-nums">
                {latest.psi_score != null ? latest.psi_score.toFixed(4) : '—'}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              {stats.map((s) => (
                <div key={s.label}>
                  <p className="mb-0.5 text-xs font-medium text-muted-foreground">{s.label}</p>
                  <p className="text-sm font-medium tabular-nums">{s.value}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trend} margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }}>
                  <Label value="Report Date" position="bottom" offset={10} style={{ fontSize: 12, fill: '#6b7280' }} />
                </XAxis>
                <YAxis tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }} />
                <Tooltip />
                <ReferenceLine y={0.10} stroke="#eab308" strokeDasharray="5 5" label={{ value: '0.10', position: 'right', fontSize: 10, fill: '#eab308' }} />
                <ReferenceLine y={0.25} stroke="#ef4444" strokeDasharray="5 5" label={{ value: '0.25', position: 'right', fontSize: 10, fill: '#ef4444' }} />
                <Line type="monotone" dataKey="psi" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 3, fill: 'hsl(var(--primary))' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/components/metrics/DriftPanel.test.tsx`
Expected: PASS (both cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/metrics/DriftPanel.tsx frontend/src/__tests__/components/metrics/DriftPanel.test.tsx
git commit -m "feat(metrics): merged DriftPanel (status + PSI trend)"
```

---

## Task 6: Diagnostics metadata-curation helper

**Files:**
- Create: `frontend/src/components/metrics/diagnostics.ts`
- Test: `frontend/src/__tests__/components/metrics/diagnostics.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/components/metrics/diagnostics.test.ts`:

```ts
import { curateMetadata, CURATED_METADATA_KEYS } from '@/components/metrics/diagnostics'

describe('curateMetadata', () => {
  it('returns only the curated keys that are present, in canonical order', () => {
    const meta = {
      split_strategy: 'temporal',
      train_size: 8000,
      test_size: 2000,
      cv_auc_mean: 0.87,
      irrelevant_key: 'ignore me',
      reference_probabilities: [0.1, 0.2],
    }
    const result = curateMetadata(meta)
    expect(result.map((r) => r.key)).toEqual(['split_strategy', 'train_size', 'test_size', 'cv_auc_mean'])
    expect(result[0]).toEqual({ key: 'split_strategy', label: 'Split Strategy', value: 'temporal' })
  })

  it('returns an empty array for null/undefined metadata', () => {
    expect(curateMetadata(null)).toEqual([])
    expect(curateMetadata(undefined)).toEqual([])
  })

  it('never exposes more than the curated allow-list', () => {
    const everything: Record<string, number> = {}
    for (const { key } of CURATED_METADATA_KEYS) everything[key] = 1
    everything.secret = 1
    expect(curateMetadata(everything).length).toBe(CURATED_METADATA_KEYS.length)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/components/metrics/diagnostics.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/components/metrics/diagnostics.ts`:

```ts
export const CURATED_METADATA_KEYS: { key: string; label: string }[] = [
  { key: 'split_strategy', label: 'Split Strategy' },
  { key: 'train_size', label: 'Train Size' },
  { key: 'test_size', label: 'Test Size' },
  { key: 'cv_auc_mean', label: 'CV AUC (mean)' },
  { key: 'cv_auc_std', label: 'CV AUC (std)' },
  { key: 'overfitting_gap', label: 'Overfitting Gap' },
  { key: 'training_time_seconds', label: 'Training Time (s)' },
  { key: 'calibration_method', label: 'Calibration Method' },
]

export interface CuratedMetadataRow {
  key: string
  label: string
  value: unknown
}

export function curateMetadata(meta: Record<string, unknown> | null | undefined): CuratedMetadataRow[] {
  if (!meta) return []
  return CURATED_METADATA_KEYS.filter(({ key }) => meta[key] !== undefined && meta[key] !== null).map(
    ({ key, label }) => ({ key, label, value: meta[key] }),
  )
}

export function formatMetadataValue(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4)
  }
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/components/metrics/diagnostics.test.ts`
Expected: PASS (all three cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/metrics/diagnostics.ts frontend/src/__tests__/components/metrics/diagnostics.test.ts
git commit -m "feat(metrics): curated metadata helper for diagnostics tab"
```

---

## Task 7: Tab wrapper components + TrainControl + ModelHeader

These are presentational compositions of existing components. Verify by typecheck (Task 9 covers the
integration tests). No new unit tests here beyond typecheck.

**Files:**
- Create: `frontend/src/components/metrics/TrainControl.tsx`
- Create: `frontend/src/components/metrics/ModelHeader.tsx`
- Create: `frontend/src/components/metrics/tabs/PerformanceTab.tsx`
- Create: `frontend/src/components/metrics/tabs/FairnessTab.tsx`
- Create: `frontend/src/components/metrics/tabs/CalibrationThresholdsTab.tsx`
- Create: `frontend/src/components/metrics/tabs/DriftTab.tsx`
- Create: `frontend/src/components/metrics/tabs/DiagnosticsTab.tsx`

- [ ] **Step 1: TrainControl**

Create `frontend/src/components/metrics/TrainControl.tsx`:

```tsx
'use client'

import { Button } from '@/components/ui/button'
import { Select, SelectItem } from '@/components/ui/select'
import { Loader2 } from 'lucide-react'

interface TrainControlProps {
  selectedAlgorithm: string
  onSelect: (value: string) => void
  onTrain: () => void
  isTraining: boolean
  label: string
}

export function TrainControl({ selectedAlgorithm, onSelect, onTrain, isTraining, label }: TrainControlProps) {
  return (
    <div className="flex items-center gap-2">
      <Select value={selectedAlgorithm} onChange={(e) => onSelect(e.target.value)}>
        <SelectItem value="xgb">XGBoost</SelectItem>
        <SelectItem value="rf">Random Forest</SelectItem>
      </Select>
      <Button onClick={onTrain} disabled={isTraining}>
        {isTraining ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {isTraining ? 'Training...' : label}
      </Button>
    </div>
  )
}
```

- [ ] **Step 2: ElapsedTimer + ModelHeader (banners live here)**

Create `frontend/src/components/metrics/ModelHeader.tsx`:

```tsx
'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Loader2, CheckCircle, XCircle } from 'lucide-react'
import { TrainControl } from './TrainControl'
import { ModelMetrics } from '@/types'

export function ElapsedTimer() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(interval)
  }, [])
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return <span>{mins > 0 ? `${mins}m ${secs}s` : `${secs}s`}</span>
}

interface ModelHeaderProps {
  metrics: ModelMetrics
  isAdmin: boolean
  selectedAlgorithm: string
  onSelect: (value: string) => void
  onTrain: () => void
  isTraining: boolean
  activeTrainingLabel: string
  trainingStatus: 'idle' | 'training' | 'success' | 'failure' | 'skipped'
  trainError: boolean
  trainErrorMessage: string | null
}

const ALGORITHM_LABELS: Record<string, string> = { rf: 'Random Forest', xgb: 'XGBoost' }

export function ModelHeader(props: ModelHeaderProps) {
  const { metrics, isAdmin, selectedAlgorithm, onSelect, onTrain, isTraining, activeTrainingLabel, trainingStatus, trainError, trainErrorMessage } = props
  const algorithmLabel = ALGORITHM_LABELS[metrics.algorithm] || metrics.algorithm

  return (
    <>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">{algorithmLabel}</h3>
          <Badge variant="secondary" className="px-3 py-0.5 text-sm">v{metrics.version}</Badge>
          {metrics.is_active && <Badge variant="success" className="px-3 py-0.5 text-sm">Active</Badge>}
        </div>
        {isAdmin && (
          <TrainControl selectedAlgorithm={selectedAlgorithm} onSelect={onSelect} onTrain={onTrain} isTraining={isTraining} label="Train New Model" />
        )}
      </div>

      {isTraining && (
        <Card className="border-blue-200 bg-gradient-to-r from-blue-50 to-indigo-50">
          <CardContent className="flex items-center gap-4 py-5">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-100">
              <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-blue-900">Training {activeTrainingLabel} model...</p>
              <p className="mt-0.5 text-sm text-blue-700">Running Optuna Bayesian optimization with 3-fold cross-validation</p>
              <div className="mt-2 flex items-center gap-4">
                <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-600">Elapsed: <ElapsedTimer /></span>
                <span className="text-xs text-blue-500">Typically 3-5 minutes</span>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {trainingStatus === 'success' && !isTraining && (
        <Card className="border-emerald-200 bg-gradient-to-r from-emerald-50 to-green-50">
          <CardContent className="flex items-center gap-3 py-4">
            <CheckCircle className="h-5 w-5 shrink-0 text-emerald-600" />
            <p className="text-sm font-medium text-emerald-800">Model training complete. Metrics have been updated.</p>
          </CardContent>
        </Card>
      )}

      {trainingStatus === 'skipped' && !isTraining && (
        <Card className="border-amber-200 bg-gradient-to-r from-amber-50 to-yellow-50">
          <CardContent className="flex items-center gap-3 py-4">
            <XCircle className="h-5 w-5 shrink-0 text-amber-600" />
            <p className="text-sm font-medium text-amber-800">Training was skipped because another training job was already in progress. The active model was not retrained.</p>
          </CardContent>
        </Card>
      )}

      {(trainError || trainingStatus === 'failure') && !isTraining && (
        <Card className="border-red-200 bg-gradient-to-r from-red-50 to-rose-50">
          <CardContent className="flex items-center gap-3 py-4">
            <XCircle className="h-5 w-5 shrink-0 text-red-600" />
            <p className="text-sm font-medium text-red-800">{trainErrorMessage || 'Model training failed. Please try again.'}</p>
          </CardContent>
        </Card>
      )}
    </>
  )
}
```

- [ ] **Step 3: PerformanceTab**

Create `frontend/src/components/metrics/tabs/PerformanceTab.tsx`:

```tsx
'use client'

import { ConfusionMatrix } from '@/components/metrics/ConfusionMatrix'
import { ROCCurve } from '@/components/metrics/ROCCurve'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import { ModelMetrics } from '@/types'

export function PerformanceTab({ metrics }: { metrics: ModelMetrics }) {
  const hasConfusion = metrics.confusion_matrix && Object.keys(metrics.confusion_matrix).length > 0
  const hasRoc = metrics.roc_curve_data?.fpr && metrics.roc_curve_data?.tpr
  const features = metrics.feature_importances
  const hasFeatures = features && (Array.isArray(features) ? features.length > 0 : Object.keys(features).length > 0)

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        {hasConfusion && <ConfusionMatrix matrix={metrics.confusion_matrix} />}
        {hasRoc && <ROCCurve fpr={metrics.roc_curve_data.fpr!} tpr={metrics.roc_curve_data.tpr!} auc={metrics.auc_roc ?? 0} />}
      </div>
      {hasFeatures && <FeatureImportance features={features} />}
    </div>
  )
}
```

- [ ] **Step 4: FairnessTab**

Create `frontend/src/components/metrics/tabs/FairnessTab.tsx`:

```tsx
'use client'

import { FairnessCard } from '@/components/metrics/FairnessCard'
import { ModelMetrics } from '@/types'

export function FairnessTab({ metrics }: { metrics: ModelMetrics }) {
  if (!metrics.fairness_metrics || Object.keys(metrics.fairness_metrics).length === 0) {
    return <p className="text-sm text-muted-foreground">No fairness analysis available for this model.</p>
  }
  return <FairnessCard fairnessMetrics={metrics.fairness_metrics} />
}
```

- [ ] **Step 5: CalibrationThresholdsTab**

Create `frontend/src/components/metrics/tabs/CalibrationThresholdsTab.tsx`:

```tsx
'use client'

import { CalibrationChart } from '@/components/metrics/CalibrationChart'
import { ThresholdChart } from '@/components/metrics/ThresholdChart'
import { ModelMetrics } from '@/types'

export function CalibrationThresholdsTab({ metrics }: { metrics: ModelMetrics }) {
  const hasCalibration = metrics.calibration_data?.fraction_of_positives
  const hasThreshold = metrics.threshold_analysis?.sweep

  if (!hasCalibration && !hasThreshold) {
    return <p className="text-sm text-muted-foreground">No calibration or threshold data available for this model.</p>
  }

  return (
    <div className="grid gap-6 md:grid-cols-2">
      {hasCalibration && (
        <CalibrationChart
          fractionOfPositives={metrics.calibration_data!.fraction_of_positives}
          meanPredictedValue={metrics.calibration_data!.mean_predicted_value}
          ece={metrics.calibration_data!.ece}
        />
      )}
      {hasThreshold && (
        <ThresholdChart
          sweep={metrics.threshold_analysis!.sweep}
          f1OptimalThreshold={metrics.threshold_analysis!.f1_optimal_threshold}
          youdenJThreshold={metrics.threshold_analysis!.youden_j_threshold}
          costOptimalThreshold={metrics.threshold_analysis!.cost_optimal_threshold}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 6: DriftTab**

Create `frontend/src/components/metrics/tabs/DriftTab.tsx`:

```tsx
'use client'

import { DriftPanel } from '@/components/metrics/DriftPanel'
import { DriftReport } from '@/types'

export function DriftTab({ reports }: { reports: DriftReport[] }) {
  return <DriftPanel reports={reports} />
}
```

- [ ] **Step 7: DiagnosticsTab**

Create `frontend/src/components/metrics/tabs/DiagnosticsTab.tsx`:

```tsx
'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DecileChart } from '@/components/metrics/DecileChart'
import { curateMetadata, formatMetadataValue } from '@/components/metrics/diagnostics'
import { ModelMetrics } from '@/types'

export function DiagnosticsTab({ metrics }: { metrics: ModelMetrics }) {
  const metadataRows = curateMetadata(metrics.training_metadata)
  const scalars = [
    { label: 'Gini', value: metrics.gini_coefficient },
    { label: 'KS Statistic', value: metrics.ks_statistic },
    { label: 'Brier Score', value: metrics.brier_score },
    { label: 'Log Loss', value: metrics.log_loss },
    { label: 'ECE', value: metrics.ece },
    { label: 'Active Threshold', value: metrics.optimal_threshold },
  ].filter((s) => s.value != null)

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        {scalars.length > 0 && (
          <Card>
            <CardHeader className="pb-4"><CardTitle className="text-base">Advanced Scalars</CardTitle></CardHeader>
            <CardContent className="px-0">
              <div className="divide-y divide-border">
                {scalars.map((s) => (
                  <div key={s.label} className="grid grid-cols-2 gap-4 px-6 py-2.5">
                    <span className="text-sm text-muted-foreground">{s.label}</span>
                    <span className="text-right font-mono text-sm tabular-nums">{(s.value as number).toFixed(4)}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
        {metadataRows.length > 0 && (
          <Card>
            <CardHeader className="pb-4"><CardTitle className="text-base">Training Metadata</CardTitle></CardHeader>
            <CardContent className="px-0">
              <div className="divide-y divide-border">
                {metadataRows.map((row) => (
                  <div key={row.key} className="grid grid-cols-2 gap-4 px-6 py-2.5">
                    <span className="text-sm text-muted-foreground">{row.label}</span>
                    <span className="truncate text-right font-mono text-sm tabular-nums" title={formatMetadataValue(row.value)}>
                      {formatMetadataValue(row.value)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
      {metrics.decile_analysis?.deciles && <DecileChart deciles={metrics.decile_analysis.deciles} />}
    </div>
  )
}
```

- [ ] **Step 8: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/metrics/TrainControl.tsx frontend/src/components/metrics/ModelHeader.tsx frontend/src/components/metrics/tabs/
git commit -m "feat(metrics): extract ModelHeader, TrainControl, and tab wrappers"
```

---

## Task 8: Recompose the page as a tabbed orchestrator

**Files:**
- Modify (full rewrite): `frontend/src/app/dashboard/model-metrics/page.tsx`

- [ ] **Step 1: Replace page.tsx with the orchestrator**

Replace the entire contents of `frontend/src/app/dashboard/model-metrics/page.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { useModelMetrics, useTrainModel } from '@/hooks/useMetrics'
import { useDriftReports } from '@/hooks/useDriftReports'
import { useAuth } from '@/lib/auth'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Cpu, Loader2, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { ModelHeader, ElapsedTimer } from '@/components/metrics/ModelHeader'
import { TrainControl } from '@/components/metrics/TrainControl'
import { KpiStrip } from '@/components/metrics/KpiStrip'
import { PerformanceTab } from '@/components/metrics/tabs/PerformanceTab'
import { FairnessTab } from '@/components/metrics/tabs/FairnessTab'
import { CalibrationThresholdsTab } from '@/components/metrics/tabs/CalibrationThresholdsTab'
import { DriftTab } from '@/components/metrics/tabs/DriftTab'
import { DiagnosticsTab } from '@/components/metrics/tabs/DiagnosticsTab'

const ALGORITHM_LABELS: Record<string, string> = { rf: 'Random Forest', xgb: 'XGBoost' }

export default function ModelMetricsPage() {
  const { data: metrics, isLoading, isError } = useModelMetrics()
  const { data: driftReports } = useDriftReports(6)
  const { user } = useAuth()
  const { trainingStatus, trainingAlgorithm, errorMessage: trainErrorMessage, ...trainModel } = useTrainModel()
  const [selectedAlgorithm, setSelectedAlgorithm] = useState('xgb')
  const isTraining = trainModel.isPending || trainingStatus === 'training'
  const isAdmin = user?.role === 'admin'
  const activeTrainingLabel = ALGORITHM_LABELS[trainingAlgorithm || selectedAlgorithm] || selectedAlgorithm

  const handleTrain = () => {
    trainModel.mutate(selectedAlgorithm, {
      onSuccess: () => toast.success('Model training started'),
      onError: (err: any) => {
        const status = err?.response?.status
        const detail = err?.response?.data?.detail || err?.response?.data?.error
        if (status === 429) toast.error(detail ? `Rate limit reached: ${detail}` : 'Training rate limit reached. Please wait a few minutes before retrying.')
        else if (status === 409) toast.error(detail || 'A training job is already in progress. Please wait for it to complete.')
        else if (status === 403) toast.error('You do not have permission to train models.')
        else if (status === 400) toast.error(detail || 'Invalid training request.')
        else toast.error('Failed to start training')
      },
    })
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="grid gap-6 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-64" />)}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="space-y-2 text-center">
          <XCircle className="mx-auto h-12 w-12 text-red-400" />
          <p className="text-muted-foreground">Failed to load model metrics</p>
          <p className="text-sm text-muted-foreground">Check that the backend is running and try refreshing the page.</p>
        </div>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="space-y-4 text-center">
          <Cpu className="mx-auto h-12 w-12 text-muted-foreground" />
          <p className="text-muted-foreground">No active model found</p>
          {isAdmin && (
            <div className="flex justify-center">
              <TrainControl selectedAlgorithm={selectedAlgorithm} onSelect={setSelectedAlgorithm} onTrain={handleTrain} isTraining={isTraining} label="Train Model" />
            </div>
          )}
          {isTraining && (
            <Card className="mt-4 border-blue-200 bg-blue-50/50">
              <CardContent className="flex items-center gap-4 py-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-100">
                  <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                </div>
                <div className="text-left">
                  <p className="font-medium text-blue-900">Training {activeTrainingLabel} model...</p>
                  <p className="text-sm text-blue-600">Running Optuna Bayesian optimization with cross-validation. Elapsed: <ElapsedTimer /></p>
                  <p className="mt-1 text-xs text-blue-500">Typically 3-5 minutes. You can navigate away — training continues in the background.</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    )
  }

  const hasDrift = !!driftReports && driftReports.length > 0

  return (
    <div className="space-y-6">
      <ModelHeader
        metrics={metrics}
        isAdmin={isAdmin}
        selectedAlgorithm={selectedAlgorithm}
        onSelect={setSelectedAlgorithm}
        onTrain={handleTrain}
        isTraining={isTraining}
        activeTrainingLabel={activeTrainingLabel}
        trainingStatus={trainingStatus}
        trainError={trainModel.isError}
        trainErrorMessage={trainErrorMessage}
      />

      <KpiStrip metrics={metrics} />

      <Tabs defaultValue="performance">
        <TabsList className="flex-wrap">
          <TabsTrigger value="performance">Performance</TabsTrigger>
          <TabsTrigger value="fairness">Fairness</TabsTrigger>
          <TabsTrigger value="calibration">Calibration &amp; Thresholds</TabsTrigger>
          {hasDrift && <TabsTrigger value="drift">Drift</TabsTrigger>}
          <TabsTrigger value="diagnostics">Diagnostics</TabsTrigger>
        </TabsList>

        <TabsContent value="performance"><PerformanceTab metrics={metrics} /></TabsContent>
        <TabsContent value="fairness"><FairnessTab metrics={metrics} /></TabsContent>
        <TabsContent value="calibration"><CalibrationThresholdsTab metrics={metrics} /></TabsContent>
        {hasDrift && <TabsContent value="drift"><DriftTab reports={driftReports} /></TabsContent>}
        <TabsContent value="diagnostics"><DiagnosticsTab metrics={metrics} /></TabsContent>
      </Tabs>
    </div>
  )
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Run the existing page test suite (must still pass)**

Run: `cd frontend && npx vitest run src/__tests__/pages/ModelMetricsPage.test.tsx`
Expected: PASS — all 5 existing cases (header, KPI labels, no-model + train, train click, training banner, error state) still green because the header + KPI strip stay above the tabs.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/dashboard/model-metrics/page.tsx
git commit -m "feat(metrics): recompose model-metrics page as tabbed orchestrator"
```

---

## Task 9: Add tab-switching tests

**Files:**
- Modify: `frontend/src/__tests__/pages/ModelMetricsPage.test.tsx`

- [ ] **Step 1: Add a richer mock + tab-switch tests**

Append inside the `describe('ModelMetricsPage', ...)` block in `ModelMetricsPage.test.tsx`:

```tsx
  it('defaults to the Performance tab and switches to Diagnostics on click', async () => {
    const richMetrics = {
      ...mockMetrics,
      gini_coefficient: 0.82,
      ks_statistic: 0.65,
      brier_score: 0.12,
      decile_analysis: { deciles: [{ decile: 1, count: 10, actual_rate: 0.1, cumulative_rate: 0.1, lift: 0.5 }] },
      training_metadata: { split_strategy: 'temporal', train_size: 8000 },
    }
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => HttpResponse.json(richMetrics)),
      http.get(`${API_URL}/ml/drift-reports/`, () => HttpResponse.json([])),
    )

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('heading', { name: 'XGBoost' })).toBeInTheDocument())

    // Performance tab is active by default → Confusion Matrix visible
    expect(screen.getByText('Confusion Matrix')).toBeInTheDocument()
    // Diagnostics content is NOT in the DOM yet (inactive tab unmounts)
    expect(screen.queryByText('Training Metadata')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Diagnostics' }))

    expect(await screen.findByText('Training Metadata')).toBeInTheDocument()
    expect(screen.getByText('Split Strategy')).toBeInTheDocument()
    // Confusion Matrix (Performance tab) is now unmounted
    expect(screen.queryByText('Confusion Matrix')).not.toBeInTheDocument()
  })

  it('hides the Drift tab when there are no drift reports', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => HttpResponse.json(mockMetrics)),
      http.get(`${API_URL}/ml/drift-reports/`, () => HttpResponse.json([])),
    )
    renderPage()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'XGBoost' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Drift' })).not.toBeInTheDocument()
  })
```

Note: if the existing `mockMetrics` lacks `feature_importances`/`roc_curve_data` the Performance tab
still renders Confusion Matrix (mock has `confusion_matrix`), so the assertions hold. Confirm the
drift endpoint path matches `mlApi.getDriftReports` — if it differs from `/ml/drift-reports/`, read
`frontend/src/lib/api.ts` for the exact path and use that in the `http.get` mock.

- [ ] **Step 2: Run the full page suite**

Run: `cd frontend && npx vitest run src/__tests__/pages/ModelMetricsPage.test.tsx`
Expected: PASS — 5 original + 2 new.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/__tests__/pages/ModelMetricsPage.test.tsx
git commit -m "test(metrics): tab-switching + conditional drift tab coverage"
```

---

## Task 10: Delete the superseded drift components + full verification

**Files:**
- Delete: `frontend/src/components/metrics/DriftOverview.tsx`
- Delete: `frontend/src/components/metrics/DriftPsiChart.tsx`

- [ ] **Step 1: Confirm no remaining importers, then delete**

Run: `cd frontend && grep -rn "DriftOverview\|DriftPsiChart" src` 
Expected: no hits outside the two files themselves (the new page uses `DriftPanel`). If a stray
`__tests__` references them, delete that test too. Then:

```bash
git rm frontend/src/components/metrics/DriftOverview.tsx frontend/src/components/metrics/DriftPsiChart.tsx
```

- [ ] **Step 2: Full frontend verification**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: typecheck clean; entire frontend suite green.

- [ ] **Step 3: Lint (host)**

Run (backend, from repo root): `python -m ruff check backend/apps/ml_engine/services/metrics.py`
Expected: no errors (confirms the removed `calibration_curve` import left no unused-import warning).

- [ ] **Step 4: Full backend metrics suite**

Run: `docker exec loan-approval-ai-system-backend-1 python -m pytest apps/ml_engine/tests/test_metrics_production_grade.py -v`
Expected: PASS.

- [ ] **Step 5: Manual visual check (the redesign is visual)**

With the stack running (`docker compose up -d`), open `http://localhost:3000/dashboard/model-metrics`
(admin login). Confirm: 5-card KPI strip with AUC hero; 5 tabs (Drift only if reports exist);
Performance default; feature importance capped with "+N more"; calibration line is straight;
confusion-matrix cells are legible (TN not washing out the rest); Diagnostics shows curated
metadata + scalars + decile chart.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(metrics): remove superseded DriftOverview/DriftPsiChart"
```

---

## Self-Review

- **Spec coverage:** IA/tabs → Tasks 7-8; decomposition (ModelHeader/KpiStrip/tabs) → Tasks 4,7,8; merged drift → Task 5; curated metadata → Task 6; decile→Diagnostics → Task 7; feature cap / calibration line / confusion colour → Tasks 2-3; weighted ECE + dead line → Task 1; tests green + new coverage → Tasks 8-9; cleanup → Task 10. All spec sections mapped.
- **Placeholders:** none — every code step has complete code; commands have expected output. The only deferred detail (exact drift-reports API path in Task 9) includes an explicit instruction to read `lib/api.ts` and a safe default.
- **Type consistency:** `KpiStrip` props match `ModelMetrics` field names; `DriftPanel`/`DriftTab` use `DriftReport`; `curateMetadata`/`formatMetadataValue`/`CURATED_METADATA_KEYS` names consistent across Task 6 and Task 7; `ModelHeader` prop names match the page's call site in Task 8; `TrainControl` props identical in both call sites.
