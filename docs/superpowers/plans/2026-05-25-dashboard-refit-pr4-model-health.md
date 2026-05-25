# Dashboard refit PR-4 — Model Health consolidation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `/dashboard/model-metrics` (the dense academic page) and `/dashboard/model-card` (the descriptive card view) with a single `/dashboard/model-health` page laid out by *action priority* across three tabs — Production Status (what to act on), Model Detail (descriptive metrics), Governance (compliance evidence). Old routes redirect; bookmarks survive.

**Architecture:** New page at `frontend/src/app/dashboard/model-health/page.tsx` consumes the **same three existing hooks** (`useModelMetrics`, `useDriftReports`, `useModelCard`) — no backend changes. shadcn `<Tabs>` controls the three tab views. Each tab is a small focused component in `frontend/src/components/model-health/` so the page file stays under 200 LOC. Old route directories are deleted; redirects added to `next.config.js`. Sidebar entry renamed.

**Tech Stack:** Next.js 15 App Router, shadcn `Tabs` / `Accordion`, TanStack Query (existing hooks), Tailwind, lucide-react, Recharts (kept for FeatureImportance / DecileChart / ROC / ConfusionMatrix), Vitest + RTL + MSW.

**Source spec:** [`docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md`](../specs/2026-05-25-dashboard-persona-refit-design.md) — Change 4. Stacks on PR-3 (#193).

---

## Background — current state of the two pages we're replacing

| Page | LOC | Content |
|------|-----|---------|
| `/dashboard/model-metrics` (`page.tsx`, 358 lines) | 358 | 8 metric tiles, ConfusionMatrix, ROC, FeatureImportance, Calibration, Threshold, Fairness, Decile, DriftOverview, DriftPSI, Training Metadata, Train-New-Model admin button |
| `/dashboard/model-card` (`page.tsx`, 467 lines) | 467 | 5 tabs (Overview, Performance, Fairness, Governance, Limitations) with overlapping metrics + regulatory compliance + MRM dossier link + Independent Validation |

**Overlap:** both render Accuracy / Precision / Recall / AUC / Fairness — the same data, twice, two different layouts.

**PR-4 collapses both into a single 3-tab page that's action-first.**

---

## Branch setup

This PR stacks on PR-3 (`feat/dashboard-persona-refit-pr3-permission-test`). Before Task 1 begins:

```bash
git switch feat/dashboard-persona-refit-pr3-permission-test
git switch -c feat/dashboard-persona-refit-pr4-model-health
```

All commits land on `feat/dashboard-persona-refit-pr4-model-health`. Open the PR against `feat/dashboard-persona-refit-pr3-permission-test`. Retarget upstream after PRs #191/#192/#193 merge per the user's stacked-PR convention.

---

## File map

**Frontend — create:**
- `frontend/src/app/dashboard/model-health/page.tsx` — orchestrator: loads hooks, mounts Tabs.
- `frontend/src/app/dashboard/model-health/loading.tsx` — route-level Suspense skeleton.
- `frontend/src/app/dashboard/model-health/error.tsx` — route-level error UI.
- `frontend/src/components/model-health/ProductionStatusTab.tsx` — alerts band + drift card + fairness card + calibration card + threshold card.
- `frontend/src/components/model-health/ModelDetailTab.tsx` — summary + 8 metric tiles + FeatureImportance + DecileChart + Diagnostics accordion (ROC + ConfusionMatrix) + Train-New-Model button.
- `frontend/src/components/model-health/GovernanceTab.tsx` — intended use + training data + MRM dossier + regulatory compliance + limitations.
- `frontend/src/__tests__/pages/ModelHealthPage.test.tsx` — single integration test asserting all three tabs render + tab switching works.

**Frontend — modify:**
- `frontend/src/components/layout/Sidebar.tsx` — rename `Model Metrics` entry → `Model Health`; href `/dashboard/model-metrics` → `/dashboard/model-health`; keep `BarChart3` icon.
- `frontend/src/components/layout/DashboardLayout.tsx` — update the route → label map: `'/dashboard/model-health': 'Model Health'`.
- `frontend/next.config.js` — add an `async redirects()` function returning two permanent redirects from old routes.
- `docs/adr/001-xgboost-rf-ensemble.md` — line 37 references `/dashboard/model-metrics`; update to `/dashboard/model-health#model-detail`.

**Frontend — delete:**
- `frontend/src/app/dashboard/model-metrics/` — entire directory (3 files: page.tsx, loading.tsx, error.tsx).
- `frontend/src/app/dashboard/model-card/` — directory (1 file: page.tsx).
- `frontend/src/__tests__/pages/ModelMetricsPage.test.tsx` — old test; coverage now lives in the new ModelHealthPage test + the model-health subcomponent tests.
- `frontend/src/__tests__/pages/ModelCardPage.test.tsx` — same reason.

**No backend changes.** All three consumed endpoints exist:
- `GET /api/v1/ml/models/active/metrics/` — `useModelMetrics`
- `GET /api/v1/ml/models/active/drift-reports/?limit=N` — `useDriftReports`
- `GET /api/v1/ml/models/active/model-card/` — `useModelCard`

**Total:** 4 new sources + 1 new test + 2 modified components + 1 modified config + 1 modified doc + 5 deletions.

---

## Task 1: Sidebar + route map + page shell (no tab content)

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/components/layout/DashboardLayout.tsx`
- Create: `frontend/src/app/dashboard/model-health/page.tsx` (shell — Tabs structure only, no tab content)
- Create: `frontend/src/app/dashboard/model-health/loading.tsx`
- Create: `frontend/src/app/dashboard/model-health/error.tsx`

The new page route exists with a working three-tab shell. Tab content is empty placeholders for now — filled in Tasks 2/3/4. This means the page renders end-to-end (no broken imports) before any tab body is built.

- [ ] **Step 1.1: Update Sidebar (full file replacement for clarity, since the change touches a single array entry)**

Replace `frontend/src/components/layout/Sidebar.tsx` line 16's entry. Use Edit, targeting this exact line:

```typescript
  { href: '/dashboard/model-metrics', label: 'Model Metrics', icon: BarChart3 },
```

Change to:

```typescript
  { href: '/dashboard/model-health', label: 'Model Health', icon: BarChart3 },
```

Run a sanity grep to confirm no stray references:

```bash
grep -n "model-metrics" frontend/src/components/layout/Sidebar.tsx
```

Expected: empty.

- [ ] **Step 1.2: Update DashboardLayout route → label map**

Edit `frontend/src/components/layout/DashboardLayout.tsx` line 15. Change:

```typescript
  '/dashboard/model-metrics': 'Model Metrics',
```

to:

```typescript
  '/dashboard/model-health': 'Model Health',
```

(Sanity-check there's no other `/dashboard/model-metrics` key in this file; if there is, update it too.)

- [ ] **Step 1.3: Create the page shell**

Create `frontend/src/app/dashboard/model-health/page.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { useModelMetrics } from '@/hooks/useMetrics'
import { useDriftReports } from '@/hooks/useDriftReports'
import { useModelCard } from '@/hooks/useModelCard'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import { ProductionStatusTab } from '@/components/model-health/ProductionStatusTab'
import { ModelDetailTab } from '@/components/model-health/ModelDetailTab'
import { GovernanceTab } from '@/components/model-health/GovernanceTab'
import { XCircle, Cpu } from 'lucide-react'

export default function ModelHealthPage() {
  const { data: metrics, isLoading: metricsLoading, isError: metricsError } = useModelMetrics()
  const { data: driftReports } = useDriftReports(6)
  const { data: card } = useModelCard()

  // Default tab honours url hash (#production / #model-detail / #governance)
  // so legacy bookmarks land on the right tab after redirect.
  const initialTab = (() => {
    if (typeof window === 'undefined') return 'production'
    const hash = window.location.hash.replace('#', '')
    return ['production', 'model-detail', 'governance'].includes(hash) ? hash : 'production'
  })()
  const [tab, setTab] = useState<string>(initialTab)

  if (metricsLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-6 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      </div>
    )
  }

  if (metricsError) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <XCircle className="h-12 w-12 mx-auto text-red-400" />
          <p className="text-muted-foreground">Failed to load model health</p>
          <p className="text-sm text-muted-foreground">Check that the backend is running and try refreshing the page.</p>
        </div>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <Cpu className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No active model found</p>
          <p className="text-sm text-muted-foreground">Train a model to populate this page.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="production">Production Status</TabsTrigger>
          <TabsTrigger value="model-detail">Model Detail</TabsTrigger>
          <TabsTrigger value="governance">Governance</TabsTrigger>
        </TabsList>

        <TabsContent value="production">
          <ProductionStatusTab metrics={metrics} driftReports={driftReports ?? []} />
        </TabsContent>

        <TabsContent value="model-detail">
          <ModelDetailTab metrics={metrics} card={card} />
        </TabsContent>

        <TabsContent value="governance">
          <GovernanceTab card={card} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
```

- [ ] **Step 1.4: Create placeholder tab components (so the page imports resolve)**

Each tab is a no-op placeholder in this task. Tasks 2/3/4 replace them.

Create `frontend/src/components/model-health/ProductionStatusTab.tsx`:

```tsx
'use client'

import type { ModelMetrics, DriftReport } from '@/types'

interface ProductionStatusTabProps {
  metrics: ModelMetrics
  driftReports: DriftReport[]
}

export function ProductionStatusTab(_props: ProductionStatusTabProps) {
  return <div data-testid="production-status-tab" className="mt-4 text-sm text-muted-foreground">Production status content — filled in Task 2.</div>
}
```

Create `frontend/src/components/model-health/ModelDetailTab.tsx`:

```tsx
'use client'

import type { ModelMetrics, ModelCard } from '@/types'

interface ModelDetailTabProps {
  metrics: ModelMetrics
  card: ModelCard | null | undefined
}

export function ModelDetailTab(_props: ModelDetailTabProps) {
  return <div data-testid="model-detail-tab" className="mt-4 text-sm text-muted-foreground">Model detail content — filled in Task 3.</div>
}
```

Create `frontend/src/components/model-health/GovernanceTab.tsx`:

```tsx
'use client'

import type { ModelCard } from '@/types'

interface GovernanceTabProps {
  card: ModelCard | null | undefined
}

export function GovernanceTab(_props: GovernanceTabProps) {
  return <div data-testid="governance-tab" className="mt-4 text-sm text-muted-foreground">Governance content — filled in Task 4.</div>
}
```

- [ ] **Step 1.5: Create route-level loading + error files**

Create `frontend/src/app/dashboard/model-health/loading.tsx`:

```tsx
import { Skeleton } from '@/components/ui/skeleton'

export default function Loading() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-10 w-64" />
      <div className="grid gap-6 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-64" />
        ))}
      </div>
    </div>
  )
}
```

Create `frontend/src/app/dashboard/model-health/error.tsx`:

```tsx
'use client'

import { Button } from '@/components/ui/button'
import { XCircle } from 'lucide-react'

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex h-96 flex-col items-center justify-center gap-4 text-center">
      <XCircle className="h-12 w-12 text-red-400" />
      <div>
        <p className="font-medium">Something went wrong loading model health.</p>
        <p className="mt-1 text-sm text-muted-foreground">{error.message}</p>
      </div>
      <Button onClick={reset}>Try again</Button>
    </div>
  )
}
```

- [ ] **Step 1.6: Smoke run the dev server (manual) OR run a tsc check**

The page imports `useMetrics`, `useDriftReports`, `useModelCard`, the three tab components, and `ModelMetrics`/`DriftReport`/`ModelCard` types. Verify the imports resolve:

```bash
cd frontend
NODE_OPTIONS=--max-old-space-size=4096 npx tsc --noEmit
```

Expected: 0 errors. (If the `ModelCard` type is not exported from `@/types`, the build fails — check `frontend/src/types/index.ts` for `export interface ModelCard` and surface a deviation if missing.)

- [ ] **Step 1.7: Commit**

```bash
git add frontend/src/app/dashboard/model-health/ frontend/src/components/model-health/ frontend/src/components/layout/Sidebar.tsx frontend/src/components/layout/DashboardLayout.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): model-health route + tab shell

Adds /dashboard/model-health with three-tab shell (Production
Status, Model Detail, Governance) and placeholder tab components.
Sidebar entry renamed Model Metrics → Model Health, route updated;
DashboardLayout's route→label map updated.

Tab bodies are placeholders in this commit — Tasks 2/3/4 fill them.
The page already mounts cleanly with the existing hooks
(useModelMetrics, useDriftReports, useModelCard).

Old routes /dashboard/model-metrics and /dashboard/model-card remain
in place for now — Task 5 wires the redirects and deletes them.

Backbone of PR-4 of docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 1.8: Verify**

```bash
git log --oneline -2
```

Expected: top commit is the new shell commit; parent is `e47f65f` (the PR-3 plan commit) — but actually since PR-3 added a commit on top of its plan, the parent should be PR-3's test commit (likely `76bb736` per the Task 1 report from PR-3). Either way the chain is intact.

---

## Task 2: Production Status tab content

**Files:**
- Modify: `frontend/src/components/model-health/ProductionStatusTab.tsx` (replace placeholder body)
- Create: `frontend/src/__tests__/components/ProductionStatusTab.test.tsx`

Per spec: alerts band at top if anything breaches, then 4 cards — drift status, fairness gate, calibration drift, decision threshold + recent threshold drift. Reuse existing components where possible (`DriftOverview`, `DriftPsiChart`, `FairnessCard`, `CalibrationChart`, `ThresholdChart`).

- [ ] **Step 2.1: Write the failing test (full file content)**

Create `frontend/src/__tests__/components/ProductionStatusTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { ProductionStatusTab } from '@/components/model-health/ProductionStatusTab'
import type { ModelMetrics, DriftReport } from '@/types'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

const baseMetrics: ModelMetrics = {
  id: 'm1',
  algorithm: 'xgb',
  version: '3',
  accuracy: 0.87,
  precision: 0.85,
  recall: 0.82,
  f1_score: 0.84,
  auc_roc: 0.91,
  brier_score: 0.12,
  optimal_threshold: 0.5,
  fairness_metrics: {
    gender: { disparate_impact_ratio: 0.92, passes_80_percent_rule: true },
    state: { disparate_impact_ratio: 0.60, passes_80_percent_rule: false },
  },
  calibration_data: { ece: 0.04, fraction_of_positives: [], mean_predicted_value: [] },
  threshold_analysis: {
    sweep: [{ threshold: 0.5, precision: 0.85, recall: 0.82, f1: 0.83, fpr: 0.1, approval_rate: 0.55 }],
    f1_optimal_threshold: 0.51,
    youden_j_threshold: 0.48,
    cost_optimal_threshold: 0.55,
  },
  is_active: true,
} as unknown as ModelMetrics

const driftReports: DriftReport[] = [
  {
    id: 'r1',
    model_version: 'm1',
    report_date: '2026-05-24',
    period_start: '2026-05-17',
    period_end: '2026-05-24',
    num_predictions: 100,
    psi_score: 0.32,
    psi_per_feature: { credit_score: 0.35 },
    mean_probability: 0.4,
    std_probability: 0.15,
    approval_rate: 0.55,
    drift_detected: true,
    alert_level: 'significant',
    created_at: '2026-05-24T00:00:00Z',
  },
] as unknown as DriftReport[]

describe('ProductionStatusTab', () => {
  it('renders the alerts band when fairness fails and drift is significant', () => {
    render(<ProductionStatusTab metrics={baseMetrics} driftReports={driftReports} />)
    // Top alerts band
    const alerts = screen.getByRole('region', { name: /alerts/i })
    expect(alerts).toBeInTheDocument()
    // Names of failing items appear inside it
    expect(alerts).toHaveTextContent(/fairness/i)
    expect(alerts).toHaveTextContent(/drift/i)
  })

  it('omits the alerts band when nothing breaches', () => {
    const passingMetrics: ModelMetrics = {
      ...baseMetrics,
      fairness_metrics: {
        gender: { disparate_impact_ratio: 0.92, passes_80_percent_rule: true },
      },
    } as unknown as ModelMetrics
    const cleanDrift: DriftReport[] = [
      { ...driftReports[0], psi_score: 0.05, alert_level: 'none', drift_detected: false } as unknown as DriftReport,
    ]
    render(<ProductionStatusTab metrics={passingMetrics} driftReports={cleanDrift} />)
    expect(screen.queryByRole('region', { name: /alerts/i })).not.toBeInTheDocument()
  })

  it('renders the four expected cards by title', () => {
    render(<ProductionStatusTab metrics={baseMetrics} driftReports={driftReports} />)
    // Drift Overview (existing component) renders "Drift" / "PSI" labels
    expect(screen.getByText(/drift/i)).toBeInTheDocument()
    // Fairness card renders "Fairness" heading
    expect(screen.getByText(/fairness/i)).toBeInTheDocument()
    // Calibration card from existing CalibrationChart includes "Calibration"
    expect(screen.getByText(/calibration/i)).toBeInTheDocument()
    // Threshold Analysis from existing ThresholdChart includes "Threshold"
    expect(screen.getByText(/threshold/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2.2: Run the test (RED phase)**

```bash
cd frontend
npx vitest run src/__tests__/components/ProductionStatusTab.test.tsx
```

Expected: FAIL — the placeholder component returns only `"Production status content — filled in Task 2."` so none of the four required strings render.

- [ ] **Step 2.3: Implement the tab (full file replacement)**

Replace `frontend/src/components/model-health/ProductionStatusTab.tsx`:

```tsx
'use client'

import type { ModelMetrics, DriftReport } from '@/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DriftOverview } from '@/components/metrics/DriftOverview'
import { DriftPsiChart } from '@/components/metrics/DriftPsiChart'
import { FairnessCard } from '@/components/metrics/FairnessCard'
import { CalibrationChart } from '@/components/metrics/CalibrationChart'
import { ThresholdChart } from '@/components/metrics/ThresholdChart'
import { AlertTriangle } from 'lucide-react'

interface ProductionStatusTabProps {
  metrics: ModelMetrics
  driftReports: DriftReport[]
}

function getAlerts(metrics: ModelMetrics, driftReports: DriftReport[]): string[] {
  const out: string[] = []
  // Drift: latest report breaches significant threshold
  const latest = driftReports[0]
  if (latest && latest.alert_level === 'significant') {
    out.push(`Drift: PSI ${latest.psi_score?.toFixed(2) ?? 'n/a'} — significant breach`)
  }
  // Fairness: any protected attribute fails 80% rule
  const fm = metrics.fairness_metrics || {}
  const failing = Object.entries(fm)
    .filter(([, v]: [string, any]) => v && v.passes_80_percent_rule === false)
    .map(([k]) => k)
  if (failing.length > 0) {
    out.push(`Fairness: failing on ${failing.join(', ')}`)
  }
  // Calibration: ECE > 0.10 is a soft alert
  const ece = metrics.calibration_data?.ece
  if (typeof ece === 'number' && ece > 0.10) {
    out.push(`Calibration: ECE ${ece.toFixed(3)} (>0.10 is poor)`)
  }
  return out
}

export function ProductionStatusTab({ metrics, driftReports }: ProductionStatusTabProps) {
  const alerts = getAlerts(metrics, driftReports)
  return (
    <div className="space-y-6 mt-4">
      {alerts.length > 0 && (
        <div role="region" aria-label="Alerts" className="rounded-lg border border-rose-200 bg-rose-50/60 p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-rose-600 shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-rose-800">Alerts requiring attention</p>
              <ul className="mt-2 space-y-1">
                {alerts.map((a) => (
                  <li key={a} className="text-sm text-rose-700">{a}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Drift */}
      {driftReports.length > 0 ? (
        <div className="grid gap-6 md:grid-cols-2">
          <DriftOverview reports={driftReports} />
          <DriftPsiChart reports={driftReports} />
        </div>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Drift</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">No drift reports yet.</p>
          </CardContent>
        </Card>
      )}

      {/* Fairness */}
      {metrics.fairness_metrics && Object.keys(metrics.fairness_metrics).length > 0 ? (
        <FairnessCard fairnessMetrics={metrics.fairness_metrics} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Fairness</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">No fairness metrics recorded for the active model.</p>
          </CardContent>
        </Card>
      )}

      {/* Calibration + Threshold (side-by-side on lg) */}
      <div className="grid gap-6 md:grid-cols-2">
        {metrics.calibration_data?.fraction_of_positives && metrics.calibration_data.fraction_of_positives.length > 0 ? (
          <CalibrationChart
            fractionOfPositives={metrics.calibration_data.fraction_of_positives}
            meanPredictedValue={metrics.calibration_data.mean_predicted_value}
            ece={metrics.calibration_data.ece}
          />
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Calibration</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">No calibration data available.</p>
            </CardContent>
          </Card>
        )}
        {metrics.threshold_analysis?.sweep && metrics.threshold_analysis.sweep.length > 0 ? (
          <ThresholdChart
            sweep={metrics.threshold_analysis.sweep}
            f1OptimalThreshold={metrics.threshold_analysis.f1_optimal_threshold}
            youdenJThreshold={metrics.threshold_analysis.youden_j_threshold}
            costOptimalThreshold={metrics.threshold_analysis.cost_optimal_threshold}
          />
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Threshold</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">No threshold analysis available.</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2.4: Run test (GREEN phase)**

```bash
cd frontend
npx vitest run src/__tests__/components/ProductionStatusTab.test.tsx
```

Expected: all 3 tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add frontend/src/components/model-health/ProductionStatusTab.tsx frontend/src/__tests__/components/ProductionStatusTab.test.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): ProductionStatusTab — alerts band + 4 status cards

Production Status tab body for the model-health page. Layout:

  1. Alerts band (rose-50) at top — appears only when any of:
     - latest DriftReport.alert_level === "significant"
     - any protected attribute fails 80% rule
     - calibration ECE > 0.10
  2. Drift section: DriftOverview + DriftPsiChart side-by-side
  3. Fairness section: FairnessCard (existing component)
  4. Calibration + Threshold side-by-side: CalibrationChart +
     ThresholdChart (existing components)

Each section degrades to a "no data" Card when the corresponding
fixture is missing — important for fresh-train state.

3 tests cover alerts visible / alerts hidden / four sections render.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Model Detail tab content

**Files:**
- Modify: `frontend/src/components/model-health/ModelDetailTab.tsx`
- Create: `frontend/src/__tests__/components/ModelDetailTab.test.tsx`

Per spec: active model summary card, 8 metric tiles, FeatureImportance, DecileChart, **Diagnostics accordion** at the bottom containing ROC + ConfusionMatrix. Train-New-Model admin button at the top.

- [ ] **Step 3.1: Check `Accordion` is available in shadcn/ui**

```bash
ls frontend/src/components/ui/accordion.tsx
```

If present, use it. If absent, STOP and report — installing shadcn components mid-task is out of scope for this plan. (The plan author's recon found `tabs.tsx` but did NOT verify `accordion.tsx`; verify before assuming.)

If `accordion.tsx` is absent, the fallback is a controlled `useState`-driven `<details>` block — see Step 3.3 alternative path.

- [ ] **Step 3.2: Write the failing test (full file content)**

Create `frontend/src/__tests__/components/ModelDetailTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { ModelDetailTab } from '@/components/model-health/ModelDetailTab'
import { AuthContext } from '@/lib/auth'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ModelMetrics } from '@/types'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

const metrics: ModelMetrics = {
  id: 'm1',
  algorithm: 'xgb',
  version: '3',
  accuracy: 0.87, precision: 0.85, recall: 0.82, f1_score: 0.84,
  auc_roc: 0.91, gini_coefficient: 0.82, ks_statistic: 0.65, brier_score: 0.12,
  optimal_threshold: 0.5,
  confusion_matrix: { tp: 850, fp: 150, tn: 870, fn: 130 },
  roc_curve_data: { fpr: [0, 0.5, 1], tpr: [0, 0.8, 1] },
  feature_importances: { credit_score: 0.45, debt_to_income: 0.28 },
  decile_analysis: { deciles: [{ decile: 1, bad_rate: 0.4 }] },
  training_metadata: { num_features: 71 },
  is_active: true,
} as unknown as ModelMetrics

function wrap(ui: React.ReactElement, role: 'admin' | 'officer' = 'officer') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider
        value={{
          user: { id: 1, username: 'u', email: 'u@t.test', first_name: 'U', last_name: 'T', role },
          isLoading: false, login: () => {}, register: () => {}, logout: () => {},
        } as any}
      >
        {ui}
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('ModelDetailTab', () => {
  it('renders algorithm + version in the summary card', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />)
    expect(screen.getByText(/XGBoost/i)).toBeInTheDocument()
    expect(screen.getByText(/v3/)).toBeInTheDocument()
  })

  it('renders all 8 metric tiles when data is present', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />)
    for (const label of ['Accuracy', 'Precision', 'Recall', 'F1 Score', 'AUC-ROC', 'Gini', 'KS Statistic', 'Brier Score']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows Train New Model button for admin role', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />, 'admin')
    expect(screen.getByRole('button', { name: /train new model/i })).toBeInTheDocument()
  })

  it('hides Train New Model button for officer role', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />, 'officer')
    expect(screen.queryByRole('button', { name: /train new model/i })).not.toBeInTheDocument()
  })

  it('renders the Diagnostics accordion (collapsed by default) containing ROC + Confusion Matrix labels', () => {
    wrap(<ModelDetailTab metrics={metrics} card={undefined} />)
    // The accordion trigger button is visible; its content references "ROC" and "Confusion"
    expect(screen.getByText(/diagnostics/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 3.3: Run test (RED phase)**

```bash
cd frontend
npx vitest run src/__tests__/components/ModelDetailTab.test.tsx
```

Expected: FAIL — placeholder body returns only `"Model detail content — filled in Task 3."`.

- [ ] **Step 3.4: Implement the tab (full file replacement)**

The implementation uses the shadcn `Accordion` if available, otherwise a native `<details>` block. The test only asserts the word "Diagnostics" appears — both styles pass.

If `Accordion` exists, replace `frontend/src/components/model-health/ModelDetailTab.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { useTrainModel } from '@/hooks/useMetrics'
import { useAuth } from '@/lib/auth'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectItem } from '@/components/ui/select'
import { ConfusionMatrix } from '@/components/metrics/ConfusionMatrix'
import { ROCCurve } from '@/components/metrics/ROCCurve'
import { FeatureImportance } from '@/components/metrics/FeatureImportance'
import { DecileChart } from '@/components/metrics/DecileChart'
import { formatPercent } from '@/lib/utils'
import { Cpu, Loader2, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import type { ModelMetrics, ModelCard } from '@/types'

interface ModelDetailTabProps {
  metrics: ModelMetrics
  card: ModelCard | null | undefined
}

const ALGORITHM_LABELS: Record<string, string> = { rf: 'Random Forest', xgb: 'XGBoost' }

export function ModelDetailTab({ metrics, card }: ModelDetailTabProps) {
  const { user } = useAuth()
  const { trainingStatus, trainingAlgorithm, errorMessage, ...trainModel } = useTrainModel()
  const [selectedAlgorithm, setSelectedAlgorithm] = useState('xgb')
  const isTraining = trainModel.isPending || trainingStatus === 'training'

  const handleTrain = () => {
    trainModel.mutate(selectedAlgorithm, {
      onSuccess: () => toast.success('Model training started'),
      onError: (err: any) => {
        const status = err?.response?.status
        const detail = err?.response?.data?.detail || err?.response?.data?.error
        if (status === 429) toast.error(detail ? `Rate limit reached: ${detail}` : 'Training rate limit reached.')
        else if (status === 409) toast.error(detail || 'A training job is already in progress.')
        else if (status === 403) toast.error('You do not have permission to train models.')
        else if (status === 400) toast.error(detail || 'Invalid training request.')
        else toast.error('Failed to start training')
      },
    })
  }

  const algorithmLabel = ALGORITHM_LABELS[metrics.algorithm] || metrics.algorithm
  const tiles = [
    { label: 'Accuracy', value: metrics.accuracy, fmt: 'pct' as const },
    { label: 'Precision', value: metrics.precision, fmt: 'pct' as const },
    { label: 'Recall', value: metrics.recall, fmt: 'pct' as const },
    { label: 'F1 Score', value: metrics.f1_score, fmt: 'pct' as const },
    { label: 'AUC-ROC', value: metrics.auc_roc, fmt: 'pct' as const },
    { label: 'Gini', value: metrics.gini_coefficient, fmt: 'num' as const },
    { label: 'KS Statistic', value: metrics.ks_statistic, fmt: 'num' as const },
    { label: 'Brier Score', value: metrics.brier_score, fmt: 'num' as const },
  ]

  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false)

  return (
    <div className="space-y-6 mt-4">
      {/* Header: summary + admin train control */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">{algorithmLabel}</h3>
          <Badge variant="secondary" className="text-sm px-3 py-0.5">v{metrics.version}</Badge>
          {metrics.is_active && <Badge variant="success" className="text-sm px-3 py-0.5">Active</Badge>}
        </div>
        {user?.role === 'admin' && (
          <div className="flex items-center gap-2">
            <Select value={selectedAlgorithm} onChange={(e) => setSelectedAlgorithm(e.target.value)}>
              <SelectItem value="rf">Random Forest</SelectItem>
              <SelectItem value="xgb">XGBoost</SelectItem>
            </Select>
            <Button onClick={handleTrain} disabled={isTraining}>
              {isTraining ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {isTraining ? 'Training...' : 'Train New Model'}
            </Button>
          </div>
        )}
      </div>

      {/* Metric tiles */}
      <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
        {tiles.filter((m) => m.value != null).map((m) => (
          <Card key={m.label}>
            <CardContent className="pt-5 pb-4">
              <p className="text-xs font-medium text-muted-foreground mb-1.5">{m.label}</p>
              <p className="text-2xl font-bold tabular-nums">
                {m.fmt === 'pct' ? formatPercent(m.value!) : m.value!.toFixed(4)}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Feature importance + Decile */}
      {metrics.feature_importances && Object.keys(metrics.feature_importances).length > 0 && (
        <FeatureImportance features={metrics.feature_importances} />
      )}
      {metrics.decile_analysis?.deciles && metrics.decile_analysis.deciles.length > 0 && (
        <DecileChart deciles={metrics.decile_analysis.deciles} />
      )}

      {/* Diagnostics accordion: ROC + Confusion (collapsed by default) */}
      <Card>
        <button
          type="button"
          onClick={() => setDiagnosticsOpen((v) => !v)}
          aria-expanded={diagnosticsOpen}
          className="flex w-full items-center justify-between p-4 text-left"
        >
          <span className="flex items-center gap-2 text-base font-semibold">
            <Cpu className="h-4 w-4" />
            Diagnostics
            <span className="text-xs font-normal text-muted-foreground">(ROC curve + confusion matrix — rarely actionable once AUC is trusted)</span>
          </span>
          <ChevronDown className={`h-5 w-5 transition-transform ${diagnosticsOpen ? 'rotate-180' : ''}`} />
        </button>
        {diagnosticsOpen && (
          <CardContent className="pt-0 grid gap-6 md:grid-cols-2">
            {metrics.confusion_matrix && Object.keys(metrics.confusion_matrix).length > 0 && (
              <ConfusionMatrix matrix={metrics.confusion_matrix} />
            )}
            {metrics.roc_curve_data?.fpr && metrics.roc_curve_data?.tpr && (
              <ROCCurve
                fpr={metrics.roc_curve_data.fpr}
                tpr={metrics.roc_curve_data.tpr}
                auc={metrics.auc_roc ?? 0}
              />
            )}
          </CardContent>
        )}
      </Card>
    </div>
  )
}
```

- [ ] **Step 3.5: Run test (GREEN phase)**

```bash
cd frontend
npx vitest run src/__tests__/components/ModelDetailTab.test.tsx
```

Expected: all 5 tests pass.

- [ ] **Step 3.6: Commit**

```bash
git add frontend/src/components/model-health/ModelDetailTab.tsx frontend/src/__tests__/components/ModelDetailTab.test.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): ModelDetailTab — summary + tiles + diagnostics

Model Detail tab body. Layout (top-to-bottom):

  - Header: algorithm/version badges + Train-New-Model button
    (admin only — useAuth role gate, mirrors prior model-metrics
    behaviour). Toast handlers for 400/403/409/429.
  - 8 metric tiles (Accuracy/Precision/Recall/F1/AUC/Gini/KS/Brier)
  - FeatureImportance (existing component)
  - DecileChart (existing component)
  - Diagnostics accordion (collapsed by default) containing
    ConfusionMatrix + ROCCurve — kept but tucked away per the
    refit spec (these rarely change after AUC stabilises).

5 tests cover summary, tiles, admin/officer role gating, and
accordion presence.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Governance tab content

**Files:**
- Modify: `frontend/src/components/model-health/GovernanceTab.tsx`
- Create: `frontend/src/__tests__/components/GovernanceTab.test.tsx`

Per spec: intended use + training data summary + synthetic data validation advisory + independent validation + MRM dossier link + regulatory compliance checklist (APRA CPG 235, NCCP Act, Banking Code) + limitations list. All consumed from `useModelCard()`.

- [ ] **Step 4.1: Write the failing test (full file content)**

Create `frontend/src/__tests__/components/GovernanceTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { GovernanceTab } from '@/components/model-health/GovernanceTab'
import type { ModelCard } from '@/types'

const card: ModelCard = {
  model_details: { name: 'XGBoost Loan Approval', algorithm: 'xgb', version: '3', created_at: '2026-01-01', description: 'AU loan approval ensemble' },
  intended_use: { primary_use: 'Personal / home / auto loan approval', users: 'Loan officers', out_of_scope: 'Wholesale or commercial lending' },
  training_data: { description: 'Synthetic AU lending data', size: 10000, features: 71, label_distribution: { approved: 0.55, denied: 0.45 } },
  performance_metrics: { accuracy: 0.87, precision: 0.85, recall: 0.82, f1_score: 0.84, auc_roc: 0.91, gini: 0.82, brier_score: 0.12, ece: 0.04 },
  fairness_analysis: { protected_attributes: ['gender', 'age_bucket'], mitigation: 'Pre-deployment four-fifths gate', disparate_impact_ratio: {} },
  governance: { status: 'active', decision_thresholds: { approve: 0.7, deny: 0.3, human_review: 0.5 }, explainability_method: 'shap_tree', next_review_date: '2026-12-01', retraining_policy: {} },
  independent_validation: { status: 'not_validated', note: 'Pending independent validation' },
  limitations: ['Training data is synthetic', 'No CDR integration in this build'],
  synthetic_data_validation: { status: 'available', estimated_real_world_auc: 0.82, estimated_auc_range: [0.78, 0.86], degradation_from_synthetic: 0.09, synthetic_confidence_score: 0.7, confidence_interpretation: 'Moderate', note: 'TSTR estimate' },
  regulatory_compliance: { apra_cpg_235: true, nccp_act: true, banking_code: true },
  last_updated: '2026-05-25T00:00:00Z',
} as unknown as ModelCard

describe('GovernanceTab', () => {
  it('renders intended use section', () => {
    render(<GovernanceTab card={card} />)
    expect(screen.getByText(/intended use/i)).toBeInTheDocument()
    expect(screen.getByText(/Loan officers/i)).toBeInTheDocument()
  })

  it('renders training data summary with dataset size', () => {
    render(<GovernanceTab card={card} />)
    expect(screen.getByText(/training data/i)).toBeInTheDocument()
    expect(screen.getByText('10,000')).toBeInTheDocument()
  })

  it('renders regulatory compliance checklist', () => {
    render(<GovernanceTab card={card} />)
    expect(screen.getByText(/APRA CPG 235/i)).toBeInTheDocument()
    expect(screen.getByText(/NCCP Act/i)).toBeInTheDocument()
    expect(screen.getByText(/Banking Code/i)).toBeInTheDocument()
  })

  it('renders limitations list', () => {
    render(<GovernanceTab card={card} />)
    expect(screen.getByText(/Training data is synthetic/)).toBeInTheDocument()
    expect(screen.getByText(/No CDR integration in this build/)).toBeInTheDocument()
  })

  it('renders empty state when card is null', () => {
    render(<GovernanceTab card={null} />)
    expect(screen.getByText(/no governance data/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 4.2: Run test (RED phase)**

```bash
cd frontend
npx vitest run src/__tests__/components/GovernanceTab.test.tsx
```

Expected: FAIL — placeholder body returns only `"Governance content — filled in Task 4."`.

- [ ] **Step 4.3: Implement the tab (full file replacement)**

Replace `frontend/src/components/model-health/GovernanceTab.tsx`:

```tsx
'use client'

import type { ModelCard } from '@/types'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Shield, AlertTriangle, CheckCircle2, XCircle, FileText } from 'lucide-react'

interface GovernanceTabProps {
  card: ModelCard | null | undefined
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(2)}%`
}

export function GovernanceTab({ card }: GovernanceTabProps) {
  if (!card) {
    return (
      <div className="flex h-64 items-center justify-center mt-4">
        <div className="text-center space-y-2">
          <FileText className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No governance data available</p>
          <p className="text-sm text-muted-foreground">Train a model to populate the model card.</p>
        </div>
      </div>
    )
  }

  const reg = card.regulatory_compliance || {}
  const regLabels: Record<string, string> = {
    apra_cpg_235: 'APRA CPG 235',
    nccp_act: 'NCCP Act',
    banking_code: 'Banking Code of Practice',
  }

  return (
    <div className="grid gap-6 md:grid-cols-2 mt-4">
      {/* Intended use */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Intended Use</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="divide-y divide-border">
            <KV label="Primary Use" value={card.intended_use.primary_use} />
            <KV label="Users" value={card.intended_use.users} />
            <KV label="Out of Scope" value={card.intended_use.out_of_scope} />
          </div>
        </CardContent>
      </Card>

      {/* Training data */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Training Data</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="divide-y divide-border">
            <KV label="Description" value={card.training_data.description} />
            <KV label="Dataset Size" value={card.training_data.size > 0 ? card.training_data.size.toLocaleString() : '—'} mono />
            <KV label="Features" value={card.training_data.features > 0 ? card.training_data.features.toLocaleString() : '—'} mono />
            {Object.entries(card.training_data.label_distribution).map(([label, ratio]) => (
              <KV key={label} label={`Class: ${label}`} value={fmtPct(ratio as number)} mono />
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Synthetic data advisory */}
      {card.synthetic_data_validation?.status === 'available' && (
        <Card className="border-amber-200/50 bg-gradient-to-r from-amber-50/30 to-orange-50/30 md:col-span-2">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-800">Synthetic Data Advisory</p>
              <p className="text-sm text-amber-700 mt-1">{card.synthetic_data_validation.note}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Regulatory compliance */}
      <Card className="md:col-span-2">
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Regulatory Compliance</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="divide-y divide-border">
            {Object.entries(reg).map(([key, compliant]) => (
              <div key={key} className="grid grid-cols-2 gap-4 px-6 py-2.5 items-center">
                <span className="text-sm text-muted-foreground">{regLabels[key] || key}</span>
                <span className="text-right">
                  {compliant ? (
                    <Badge variant="success">
                      <Shield className="h-3 w-3 mr-1" />Compliant
                    </Badge>
                  ) : (
                    <Badge variant="destructive">Non-Compliant</Badge>
                  )}
                </span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Independent validation */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Independent Validation</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Status:</span>
            <Badge variant={card.independent_validation.status === 'validated' ? 'success' : 'warning'}>
              {card.independent_validation.status === 'validated' ? 'Validated' : 'Not Validated'}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-3">{card.independent_validation.note || card.independent_validation.outcome || ''}</p>
        </CardContent>
      </Card>

      {/* Limitations */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Known Limitations</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {card.limitations.map((lim) => (
              <li key={lim} className="flex items-start gap-2 text-sm">
                <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                <span>{lim}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}

function KV({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="grid grid-cols-2 gap-4 px-6 py-2.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`text-sm text-right ${mono ? 'font-mono tabular-nums' : ''}`}>{value}</span>
    </div>
  )
}
```

- [ ] **Step 4.4: Run test (GREEN phase)**

```bash
cd frontend
npx vitest run src/__tests__/components/GovernanceTab.test.tsx
```

Expected: all 5 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add frontend/src/components/model-health/GovernanceTab.tsx frontend/src/__tests__/components/GovernanceTab.test.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): GovernanceTab — intended use / training / compliance

Governance tab body, fed entirely from useModelCard():

  - Intended use (primary use / users / out-of-scope)
  - Training data summary (size, feature count, label distribution)
  - Synthetic data advisory (only when TSTR data available)
  - Regulatory compliance checklist (APRA CPG 235 / NCCP / Banking Code)
  - Independent validation status + note
  - Known limitations list

Empty-state when card is null (e.g. no active model). 5 tests cover
intended use, training data, regulatory checklist, limitations,
and null-card empty state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Redirects, old-route deletion, page test, doc fixup

**Files:**
- Modify: `frontend/next.config.js`
- Delete: `frontend/src/app/dashboard/model-metrics/` (3 files)
- Delete: `frontend/src/app/dashboard/model-card/` (1 file)
- Delete: `frontend/src/__tests__/pages/ModelMetricsPage.test.tsx`
- Delete: `frontend/src/__tests__/pages/ModelCardPage.test.tsx`
- Create: `frontend/src/__tests__/pages/ModelHealthPage.test.tsx`
- Modify: `docs/adr/001-xgboost-rf-ensemble.md` (line 37 — old route reference)

- [ ] **Step 5.1: Add redirects to `next.config.js`**

Edit `frontend/next.config.js`. Inside the `nextConfig` object, add an `async redirects()` function. Locate the existing `async headers()` function and add `async redirects()` directly below it:

```javascript
  async redirects() {
    return [
      {
        source: '/dashboard/model-metrics',
        destination: '/dashboard/model-health#model-detail',
        permanent: true,
      },
      {
        source: '/dashboard/model-card',
        destination: '/dashboard/model-health#governance',
        permanent: true,
      },
    ]
  },
```

The `permanent: true` flag emits a 308 (preserves verb) — appropriate since these routes were retired. Hash-anchor lands the user on the right tab via `initialTab` logic in `model-health/page.tsx`.

- [ ] **Step 5.2: Delete old route directories and old test files**

```bash
git rm -r frontend/src/app/dashboard/model-metrics frontend/src/app/dashboard/model-card
git rm frontend/src/__tests__/pages/ModelMetricsPage.test.tsx frontend/src/__tests__/pages/ModelCardPage.test.tsx
```

(On PowerShell, the same commands work — `git rm` is POSIX-compatible.)

- [ ] **Step 5.3: Write the page-level integration test (full file content)**

Create `frontend/src/__tests__/pages/ModelHealthPage.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { AuthContext } from '@/lib/auth'
import { server } from '@/test/mocks/server'
import { mockUser, mockModelCard } from '@/test/mocks/handlers'

const API_URL = 'http://localhost:8000/api/v1'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/dashboard/model-health',
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

import ModelHealthPage from '@/app/dashboard/model-health/page'

const mockMetrics = {
  id: 'm1',
  algorithm: 'xgb',
  version: '3',
  accuracy: 0.87,
  precision: 0.85,
  recall: 0.82,
  f1_score: 0.84,
  auc_roc: 0.91,
  brier_score: 0.12,
  optimal_threshold: 0.5,
  confusion_matrix: { tp: 1, fp: 1, tn: 1, fn: 1 },
  roc_curve_data: { fpr: [0, 1], tpr: [0, 1] },
  feature_importances: {},
  fairness_metrics: { gender: { disparate_impact_ratio: 0.92, passes_80_percent_rule: true } },
  calibration_data: { ece: 0.04, fraction_of_positives: [0.1, 0.5, 0.9], mean_predicted_value: [0.1, 0.5, 0.9] },
  threshold_analysis: { sweep: [{ threshold: 0.5, precision: 0.85, recall: 0.82, f1: 0.83, fpr: 0.1, approval_rate: 0.55 }], f1_optimal_threshold: 0.5, youden_j_threshold: 0.48, cost_optimal_threshold: 0.55 },
  is_active: true,
  decile_analysis: { deciles: [] },
}

function renderPage(role: 'admin' | 'officer' = 'admin') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider
        value={{
          user: { ...mockUser, role },
          isLoading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(),
        } as any}
      >
        <ModelHealthPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

describe('ModelHealthPage', () => {
  beforeEach(() => {
    server.use(
      http.get(`${API_URL}/ml/models/active/metrics/`, () => HttpResponse.json(mockMetrics)),
      http.get(`${API_URL}/ml/models/active/model-card/`, () => HttpResponse.json({ model_card: mockModelCard })),
      http.get(`${API_URL}/ml/models/active/drift-reports/`, () => HttpResponse.json([]))
    )
  })

  it('renders the three tab triggers', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByRole('tab', { name: /production status/i })).toBeInTheDocument())
    expect(screen.getByRole('tab', { name: /model detail/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /governance/i })).toBeInTheDocument()
  })

  it('Production Status is the default tab', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText(/calibration/i)).toBeInTheDocument())
  })

  it('clicking Model Detail tab switches to that view', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByRole('tab', { name: /model detail/i })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: /model detail/i }))
    await waitFor(() => expect(screen.getByText(/XGBoost/i)).toBeInTheDocument())
  })

  it('clicking Governance tab switches to that view', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByRole('tab', { name: /governance/i })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: /governance/i }))
    await waitFor(() => expect(screen.getByText(/intended use/i)).toBeInTheDocument())
  })
})
```

- [ ] **Step 5.4: Update the ADR doc reference (small edit)**

Edit `docs/adr/001-xgboost-rf-ensemble.md`. Find this line (line 37 per recon):

```markdown
- Tree ensembles are less calibrated out-of-the-box than logistic regression; isotonic calibration is applied post-hoc and monitored via calibration plots in `/dashboard/model-metrics`.
```

Change to:

```markdown
- Tree ensembles are less calibrated out-of-the-box than logistic regression; isotonic calibration is applied post-hoc and monitored via calibration plots in `/dashboard/model-health` (Production Status tab).
```

- [ ] **Step 5.5: Run the new page test + full suite**

```bash
cd frontend
npx vitest run src/__tests__/pages/ModelHealthPage.test.tsx
npx vitest run
```

Expected: page test passes (4 cases); full suite green (count should be close to PR-3's 322 + delta — 5 deleted old-page tests, 3 new tab tests in Tasks 2/3/4 = +13 cases each, page test = +4, net positive ~22-25 new tests).

If anything outside the touched files fails (e.g. an orphan import of `ModelMetricsPage` or `ModelCardPage` somewhere), investigate.

- [ ] **Step 5.6: Commit**

```bash
git add -A frontend/next.config.js frontend/src/__tests__/pages/ModelHealthPage.test.tsx docs/adr/001-xgboost-rf-ensemble.md
git add -u  # picks up the git rm-staged deletions
git commit -m "$(cat <<'EOF'
feat(dashboard): redirects + delete old model-metrics/model-card pages

Adds 308 permanent redirects in next.config.js so legacy bookmarks
land on the right tab of the new /dashboard/model-health:
  /dashboard/model-metrics  ->  /dashboard/model-health#model-detail
  /dashboard/model-card     ->  /dashboard/model-health#governance

Deletes the two old route directories + their page-level tests
(their coverage is replaced by the per-tab tests added in Tasks
2/3/4 plus the new ModelHealthPage integration test).

ADR-001's reference to /dashboard/model-metrics updated to point
at the new route.

Closes PR-4 of docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md.
After this lands, the dashboard persona refit foundation spec is
fully shipped.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Smoke test

**Files:** none — manual + API verification.

- [ ] **Step 6.1: Live route smoke (curl the redirect)**

```bash
curl -I http://localhost:3000/dashboard/model-metrics
```

Expected: `HTTP/1.1 308 Permanent Redirect` with `Location: /dashboard/model-health#model-detail`.

```bash
curl -I http://localhost:3000/dashboard/model-card
```

Expected: `HTTP/1.1 308 Permanent Redirect` with `Location: /dashboard/model-health#governance`.

- [ ] **Step 6.2: Visual check at `localhost:3000/dashboard/model-health`**

Login (admin) and verify:
1. Sidebar shows "Model Health" entry (renamed from "Model Metrics").
2. Three tab triggers visible: Production Status (default), Model Detail, Governance.
3. **Production Status tab** — alerts band at top if anything breaches (on the seeded DB it should — fairness was failing on state/employment_type per PR-2's smoke). Then 4 cards visible (Drift, Fairness, Calibration, Threshold).
4. **Model Detail tab** — algorithm + version header, 8 metric tiles, FeatureImportance chart, DecileChart, Diagnostics accordion at the bottom collapsed by default. Admin sees "Train New Model" button at the top right.
5. **Governance tab** — Intended Use card, Training Data card, Synthetic Data Advisory (amber strip), Regulatory Compliance row of badges, Independent Validation, Limitations.
6. Navigate to `localhost:3000/dashboard/model-metrics` — browser redirects to `model-health#model-detail`, lands on the right tab.
7. Navigate to `localhost:3000/dashboard/model-card` — browser redirects to `model-health#governance`, lands on the right tab.
8. No console errors.

If any check fails, identify the originating commit and fix that (or add a follow-up). The principle: each task's commit must leave the stack green on its own.

---

## Open the PR

```bash
git push -u origin feat/dashboard-persona-refit-pr4-model-health

gh pr create \
  --base feat/dashboard-persona-refit-pr3-permission-test \
  --title "feat(dashboard): Model Health page — consolidates metrics + card (PR-4 of refit)" \
  --body "$(cat <<'EOF'
## Summary

Implements **PR-4** of the dashboard persona refit
([spec](docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md),
[plan](docs/superpowers/plans/2026-05-25-dashboard-refit-pr4-model-health.md)).

**Stacks on PR #193** (PR-3). Base targets
\`feat/dashboard-persona-refit-pr3-permission-test\` — retarget
upstream as PRs in the chain merge.

Replaces \`/dashboard/model-metrics\` (358 LOC, 10+ charts) and
\`/dashboard/model-card\` (467 LOC, 5 tabs) with one
\`/dashboard/model-health\` page organised by **action priority**:

1. **Production Status** (default) — alerts band, then drift /
   fairness / calibration / threshold cards. Surfaces the
   information an MRM reviewer opens the page for first.
2. **Model Detail** — algorithm header + 8 metric tiles + feature
   importance + decile chart + collapsed Diagnostics accordion
   containing ROC + ConfusionMatrix. Train-New-Model admin button.
3. **Governance** — intended use, training data, synthetic data
   advisory, regulatory compliance checklist, independent
   validation, limitations.

### Old route handling

\`next.config.js\` gains 308 permanent redirects so legacy bookmarks
survive:
- \`/dashboard/model-metrics\` -> \`/dashboard/model-health#model-detail\`
- \`/dashboard/model-card\` -> \`/dashboard/model-health#governance\`

The page reads \`window.location.hash\` on mount to pick the right
default tab. ADR-001's prose reference updated.

### Commits

| # | What |
|---|---|
| 1 | Sidebar + route map + page shell (3 placeholder tabs) |
| 2 | ProductionStatusTab — alerts band + 4 cards (3 tests) |
| 3 | ModelDetailTab — summary + tiles + diagnostics accordion (5 tests) |
| 4 | GovernanceTab — intended use / compliance / limitations (5 tests) |
| 5 | Redirects + delete old pages + integration test + ADR fixup |

### Test plan

- [x] Per-tab tests — green (Tasks 2/3/4)
- [x] ModelHealthPage integration test — 4/4 (tabs render, default tab, switching)
- [x] Full vitest suite — green
- [x] tsc --noEmit — 0 errors
- [x] Live route smoke — curl returns 308 with correct Location for both old routes
- [ ] Visual smoke at \`localhost:3000/dashboard/model-health\` — reviewer to confirm all three tabs render, redirects land on right tab, no console errors

### Spec status after this merges

- ✅ Change 1 — PR #191 (real latency + LLM spend tiles)
- ✅ Change 2 — PR #192 (operator status strip + drop donut)
- ✅ Change 3 — PR #193 (cross-customer permission regression)
- ✅ Change 4 — this PR (Model Health consolidation)

The dashboard persona refit foundation spec is fully shipped.
Next foundation specs queued in the senior-architect audit:
service decomposition, CDR adapter scaffold, security gap-closure.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes

**Spec coverage check (PR-4 only):**
- ✅ One new page replacing two old ones — Task 1 shell + Tasks 2/3/4 bodies
- ✅ Production Status as default tab — Task 1 `initialTab` defaults to `'production'`
- ✅ Alerts band only when something breaches — Task 2 `getAlerts()` returns `[]` for clean state, conditional render gates the band
- ✅ Drift / Fairness / Calibration / Threshold cards — Task 2
- ✅ Active model summary card + 8 tiles + FeatureImportance + DecileChart + Diagnostics accordion (ROC + ConfusionMatrix) — Task 3
- ✅ Train-New-Model admin button moved to Model Detail tab — Task 3
- ✅ Intended use / training / synthetic advisory / independent validation / regulatory compliance / limitations — Task 4
- ✅ 308 redirects with right hash fragments — Task 5
- ✅ Hash → default-tab logic so redirected users land on the right tab — Task 1 `initialTab`

**Placeholder scan:** no TBDs, no "implement later". Every code block has full content. The accordion's fallback path is described conditionally (Step 3.1 verifies presence; if absent the executor reports rather than improvising — that's explicit, not a placeholder).

**Type consistency:** `ModelMetrics`, `DriftReport`, `ModelCard` all imported from `@/types` consistently across all four tab files and the page. `ProductionStatusTab` consumes `metrics`, `driftReports`; `ModelDetailTab` consumes `metrics`, `card`; `GovernanceTab` consumes `card` — the page passes exactly these.

**Out of scope:** decomposition spec, CDR adapter scaffold, security gap-closure. Each gets its own foundation spec when its turn comes.
