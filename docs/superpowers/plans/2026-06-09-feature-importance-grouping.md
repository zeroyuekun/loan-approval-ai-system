# Feature Importance Chart — Grouping & Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Model Metrics "Feature Importance" chart honest and complete — collapse one-hot dummies into one bar per categorical, show all *used* features (top-20 + an "Other" rollup + a "Show all" toggle), disclose zero-importance/unused features with a footer count, and add an algorithm-neutral caption explaining what the number means.

**Architecture:** Frontend-only change to one React component. Extract two pure, exported helper functions (`buildFeatureImportanceModel`, `selectShownBars`) so the grouping/selection logic is unit-testable with exact numbers, then wire them into the existing `FeatureImportance` component. The backend already returns every feature's normalised importance; no backend change and no model retrain.

**Tech Stack:** Next.js (React 19, client component), TypeScript, recharts, Tailwind/shadcn UI, Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-06-09-feature-importance-chart-honesty-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `frontend/src/components/metrics/FeatureImportance.tsx` | Renders the chart; now also exports pure grouping/selection helpers | Modify |
| `frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx` | Unit tests for the helpers + render tests for the component | Rewrite |

No other files. `PerformanceTab.tsx` passes `metrics.feature_importances` straight through (unchanged). The `ModelMetrics`/prediction TS types are unchanged (input shape is unchanged).

**Run all commands from the `frontend/` directory.** The project convention is `npx vitest run` (NOT `npm test`).

---

## Background the engineer needs

The component currently receives `features` in one of two shapes (both must keep working):

```ts
Record<string, number>                              // { "credit_score": 0.23, "state_nsw": 0.01, ... }
Array<{ feature: string; importance: number }>      // [{ feature: "credit_score", importance: 0.23 }, ...]
```

Feature keys are **raw post-one-hot column names**. Categorical features are exploded into dummies that all share a `name_` prefix (e.g. `state_nsw`, `state_vic`). The backend (`backend/apps/ml_engine/services/training/trainer.py`) defines exactly these 8 categoricals in `ModelTrainer.CATEGORICAL_COLS`:
`purpose, home_ownership, employment_type, applicant_type, state, savings_trend_3m, industry_risk_tier, industry_anzsic`.

XGBoost's `feature_importances_` is **normalised to sum to 1.0**, so summing a categorical's dummy shares yields that categorical's total share — the correct aggregation. Importances are rounded to 4 dp by the backend, so unused/low-share features can be exactly `0`.

The current component (lines as of this plan): defines a large `FEATURE_LABELS` map (lines 14–113) and `formatFeatureName` (115–116), normalises input to `data`, filters `importance > 0`, sorts desc, then hard-caps at `const TOP_N = 15` and renders a `+N more features not shown` footer. **Keep `FEATURE_LABELS` exactly as-is.**

---

## Task 1: Extract & unit-test the pure grouping/selection logic

Add two exported pure functions to the component module and prove them with exact-number unit tests. The component's rendered output is **not** changed in this task (it still uses its existing inline logic) — we are only adding tested, reusable helpers and replacing the stale top-15 tests with logic tests.

**Files:**
- Modify: `frontend/src/components/metrics/FeatureImportance.tsx` (add helpers near the top, below `formatFeatureName`)
- Rewrite: `frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx`

- [ ] **Step 1: Replace the test file with the logic tests (these will fail to import)**

Overwrite `frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx` with:

```tsx
import { render, screen } from '@testing-library/react'
import {
  FeatureImportance,
  buildFeatureImportanceModel,
  selectShownBars,
} from '@/components/metrics/FeatureImportance'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

describe('buildFeatureImportanceModel', () => {
  it('collapses one-hot dummies into a single parent bar (summed)', () => {
    const model = buildFeatureImportanceModel({
      state_nsw: 0.05,
      state_vic: 0.03,
      state_qld: 0.02,
      credit_score: 0.4,
    })
    const state = model.charted.find((b) => b.name === 'State')
    expect(state).toBeDefined()
    expect(state!.importance).toBeCloseTo(0.1, 6)
    expect(model.charted.some((b) => b.name === 'State: NSW')).toBe(false)
  })

  it('does not capture numeric look-alikes into a categorical group', () => {
    const model = buildFeatureImportanceModel({
      employment_length: 0.2,
      employment_stability: 0.1,
      employment_type_payg_permanent: 0.05,
      savings_balance: 0.15,
      savings_to_loan_ratio: 0.07,
      savings_trend_3m_positive: 0.04,
    })
    const names = model.charted.map((b) => b.name)
    expect(names).toContain('Employment Length')
    expect(names).toContain('Employment Stability')
    expect(names).toContain('Savings Balance')
    expect(names).toContain('Savings-to-Loan Ratio')
    expect(names).toContain('Employment Type')
    expect(names).toContain('Savings Trend (3m)')
    const empType = model.charted.find((b) => b.name === 'Employment Type')
    expect(empType!.importance).toBeCloseTo(0.05, 6)
  })

  it('counts zero-importance (unused) features instead of charting them', () => {
    const model = buildFeatureImportanceModel({
      credit_score: 0.5,
      annual_income: 0.3,
      monthly_rent: 0,
      applicant_type_single: 0,
      applicant_type_couple: 0,
    })
    expect(model.charted.map((b) => b.name)).toEqual(['Credit Score', 'Annual Income'])
    expect(model.unusedCount).toBe(2)
    expect(model.total).toBe(2)
  })

  it('groups array input identically to record input', () => {
    const record = buildFeatureImportanceModel({ state_nsw: 0.05, state_vic: 0.05, credit_score: 0.4 })
    const array = buildFeatureImportanceModel([
      { feature: 'state_nsw', importance: 0.05 },
      { feature: 'state_vic', importance: 0.05 },
      { feature: 'credit_score', importance: 0.4 },
    ])
    expect(array.charted).toEqual(record.charted)
  })
})

describe('selectShownBars', () => {
  function rankedFeatures(n: number): Record<string, number> {
    const out: Record<string, number> = {}
    for (let i = 0; i < n; i++) out[`feat_${i}`] = (n - i) / n
    return out
  }

  it('rolls the tail into an "Other" bar that conserves the tail sum', () => {
    const { charted } = buildFeatureImportanceModel(rankedFeatures(25))
    const shown = selectShownBars(charted, false)
    expect(shown).toHaveLength(21)
    const other = shown[shown.length - 1]
    expect(other.isOther).toBe(true)
    expect(other.name).toBe('Other (5 features)')
    const tailSum = charted.slice(20).reduce((a, b) => a + b.importance, 0)
    expect(other.importance).toBeCloseTo(tailSum, 6)
  })

  it('counts grouped units in "Other", not raw dummy columns', () => {
    const features: Record<string, number> = {}
    for (let i = 0; i < 20; i++) features[`feat_${i}`] = 1 - i * 0.01
    ;['nsw', 'vic', 'qld', 'wa', 'sa', 'tas', 'act', 'nt'].forEach(
      (s, i) => (features[`state_${s}`] = 0.001 * (i + 1)),
    )
    const { charted } = buildFeatureImportanceModel(features)
    expect(charted).toHaveLength(21)
    const shown = selectShownBars(charted, false)
    const other = shown[shown.length - 1]
    expect(other.isOther).toBe(true)
    expect(other.name).toBe('Other (1 feature)')
  })

  it('shows no "Other" bar when 20 or fewer charted features', () => {
    const { charted } = buildFeatureImportanceModel(rankedFeatures(10))
    const shown = selectShownBars(charted, false)
    expect(shown).toHaveLength(10)
    expect(shown.some((b) => b.isOther)).toBe(false)
  })

  it('expanded shows the full charted set with no "Other" bar', () => {
    const { charted } = buildFeatureImportanceModel(rankedFeatures(25))
    const shown = selectShownBars(charted, true)
    expect(shown).toHaveLength(25)
    expect(shown.some((b) => b.isOther)).toBe(false)
  })

  it('realistic mixed shape exceeds 20 grouped features so the rollup is live', () => {
    const features: Record<string, number> = {}
    for (let i = 0; i < 30; i++) features[`num_${i}`] = 1 - i * 0.01
    ;['nsw', 'vic', 'qld'].forEach((s, i) => (features[`state_${s}`] = 0.02 * (i + 1)))
    ;['a', 'b', 'c', 'e', 'g'].forEach((s, i) => (features[`industry_anzsic_${s}`] = 0.01 * (i + 1)))
    const { charted } = buildFeatureImportanceModel(features)
    expect(charted.length).toBe(32)
    expect(charted.length).toBeGreaterThan(20)
    expect(selectShownBars(charted, false).some((b) => b.isOther)).toBe(true)
  })
})
```

- [ ] **Step 2: Run the logic tests to verify they fail**

Run (from `frontend/`):
```
npx vitest run src/__tests__/components/metrics/FeatureImportance.test.tsx
```
Expected: FAIL — `buildFeatureImportanceModel`/`selectShownBars` are not exported (import error / "is not a function").

- [ ] **Step 3: Add the exported helpers to the component module**

In `frontend/src/components/metrics/FeatureImportance.tsx`, **replace** the current `formatFeatureName` arrow (current lines ~115–116):

```tsx
  const formatFeatureName = (s: string) =>
    FEATURE_LABELS[s] ?? s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
```

with module-scope helpers **placed above the `FeatureImportance` component** (after the `FEATURE_LABELS` declaration). Add the `CATEGORY_GROUPS` map, prefix list, `TOP_N`, and the two exported functions:

```tsx
// One-hot dummy prefix → parent categorical label. Mirrors
// ModelTrainer.CATEGORICAL_COLS in
// backend/apps/ml_engine/services/training/trainer.py — keep in sync if a
// categorical is added there. An unmatched categorical degrades gracefully
// (renders as individual dummy bars); it is never silently wrong.
const CATEGORY_GROUPS: Record<string, string> = {
  state_: 'State',
  industry_anzsic_: 'Industry (ANZSIC)',
  industry_risk_tier_: 'Industry Risk Tier',
  purpose_: 'Loan Purpose',
  home_ownership_: 'Home Ownership',
  employment_type_: 'Employment Type',
  applicant_type_: 'Applicant Type',
  savings_trend_3m_: 'Savings Trend (3m)',
}
// Match the most specific (longest) prefix first.
const CATEGORY_PREFIXES = Object.keys(CATEGORY_GROUPS).sort((a, b) => b.length - a.length)

const TOP_N = 20

function formatFeatureName(s: string): string {
  return FEATURE_LABELS[s] ?? s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function parentLabelFor(rawKey: string): string | null {
  for (const prefix of CATEGORY_PREFIXES) {
    if (rawKey.startsWith(prefix)) return CATEGORY_GROUPS[prefix]
  }
  return null
}

function toEntries(
  features: Record<string, number> | Array<{ feature: string; importance: number }>,
): Array<{ feature: string; importance: number }> {
  if (Array.isArray(features)) {
    return features.filter(
      (f): f is { feature: string; importance: number } =>
        f != null && typeof f === 'object' && 'feature' in f && 'importance' in f,
    )
  }
  return Object.entries(features).map(([feature, importance]) => ({ feature, importance: Number(importance) }))
}

export interface FeatureBar {
  name: string
  importance: number
  isOther?: boolean
}

export interface FeatureImportanceModel {
  charted: FeatureBar[]
  unusedCount: number
  total: number
}

/**
 * Collapse one-hot dummies into parent categoricals, then split into the
 * charted set (importance > 0, sorted desc) and a count of unused features
 * (importance rounds to 0 — the model never split on them).
 */
export function buildFeatureImportanceModel(
  features: Record<string, number> | Array<{ feature: string; importance: number }>,
): FeatureImportanceModel {
  const groups = new Map<string, number>()
  for (const { feature, importance } of toEntries(features)) {
    const imp = Number(importance)
    if (!Number.isFinite(imp)) continue
    const label = parentLabelFor(feature) ?? formatFeatureName(feature)
    groups.set(label, (groups.get(label) ?? 0) + imp)
  }
  const grouped: FeatureBar[] = Array.from(groups.entries()).map(([name, importance]) => ({ name, importance }))
  const charted = grouped.filter((d) => d.importance > 0).sort((a, b) => b.importance - a.importance)
  return { charted, unusedCount: grouped.length - charted.length, total: charted.length }
}

/** Collapsed view = top N + an "Other (k features)" rollup; expanded = full charted set. */
export function selectShownBars(charted: FeatureBar[], expanded: boolean, topN: number = TOP_N): FeatureBar[] {
  if (expanded || charted.length <= topN) return charted
  const tail = charted.slice(topN)
  const otherSum = tail.reduce((acc, d) => acc + d.importance, 0)
  return [
    ...charted.slice(0, topN),
    { name: `Other (${tail.length} feature${tail.length === 1 ? '' : 's'})`, importance: otherSum, isOther: true },
  ]
}
```

> Note: `formatFeatureName` is now a module-scope `function` instead of a `const` inside the component. The component body still references `formatFeatureName(...)` in its existing inline `data` mapping — that call keeps working unchanged (it now resolves to the module-scope function). We rewire the component body in Task 2.
>
> Expected transient state after this task: the component still contains its **existing** inner `const TOP_N = 15` and `data`/`slice(0, 15)` logic, which shadows the new module-scope `const TOP_N = 20`. This shadow is intentional and short-lived — Task 2 replaces the whole component body and removes the inner `TOP_N`. Task 1 only runs Vitest (no eslint/tsc), so the shadow surfaces no error; lint/type-check run in Task 3 after the shadow is gone. Do not "fix" the rendered chart in this task.

- [ ] **Step 4: Run the logic tests to verify they pass**

Run (from `frontend/`):
```
npx vitest run src/__tests__/components/metrics/FeatureImportance.test.tsx
```
Expected: PASS — all `buildFeatureImportanceModel` and `selectShownBars` tests green.

- [ ] **Step 5: Commit**

```
git add frontend/src/components/metrics/FeatureImportance.tsx frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx
git commit -m "feat(metrics): pure grouping + bar-selection helpers for feature importance"
```

---

## Task 2: Rewire the component (grouped chart, Other rollup, toggle, caption, footer, a11y)

Now make the rendered chart use the helpers, add the caption, the "Show all" toggle, the unused-feature footer disclosure, and the state-aware accessibility labels.

**Files:**
- Modify: `frontend/src/components/metrics/FeatureImportance.tsx` (imports + component body)
- Modify: `frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx` (add render tests)

- [ ] **Step 1: Add the render tests (they will fail against the current body)**

Add `fireEvent` to the testing-library import at the top of the test file:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
```

Append this describe block to the **end** of `frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx`:

```tsx
describe('<FeatureImportance />', () => {
  function rankedRecord(n: number): Record<string, number> {
    const out: Record<string, number> = {}
    for (let i = 0; i < n; i++) out[`feat_${i}`] = (n - i) / n
    return out
  }

  it('renders the honest, algorithm-neutral caption', () => {
    render(<FeatureImportance features={{ credit_score: 0.5 }} />)
    expect(screen.getByText(/normalised tree-based importance/i)).toBeInTheDocument()
    expect(screen.getByText(/magnitude only/i)).toBeInTheDocument()
  })

  it('discloses unused (zero-importance) features in the footer', () => {
    render(
      <FeatureImportance features={{ credit_score: 0.6, annual_income: 0.4, monthly_rent: 0, hem_gap: 0 }} />,
    )
    expect(screen.getByText(/2 features had no measurable contribution/i)).toBeInTheDocument()
  })

  it('omits the footer disclosure when every feature is used', () => {
    render(<FeatureImportance features={{ credit_score: 0.6, annual_income: 0.4 }} />)
    expect(screen.queryByText(/no measurable contribution/i)).not.toBeInTheDocument()
  })

  it('shows a "Show all" toggle when >20 features, and expands to all', () => {
    render(<FeatureImportance features={rankedRecord(25)} />)
    const toggle = screen.getByRole('button', { name: /show all 25 features/i })
    expect(toggle).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: /plus an Other bar aggregating 5 more features/i }),
    ).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: /show fewer/i })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /all 25 grouped features/i })).toBeInTheDocument()
  })

  it('omits the toggle when 20 or fewer features', () => {
    render(<FeatureImportance features={{ credit_score: 0.6, annual_income: 0.4 }} />)
    expect(screen.queryByRole('button', { name: /show all|show fewer/i })).not.toBeInTheDocument()
  })

  it('keeps the synthetic "Other" bar out of the screen-reader feature list', () => {
    render(<FeatureImportance features={rankedRecord(25)} />)
    const srList = screen.getByRole('list', { name: 'Feature importance list' })
    expect(srList.textContent).not.toMatch(/Other \(/)
  })
})
```

- [ ] **Step 2: Run the render tests to verify they fail**

Run (from `frontend/`):
```
npx vitest run src/__tests__/components/metrics/FeatureImportance.test.tsx -t "FeatureImportance />"
```
Expected: FAIL — current body has no caption, no toggle, no unused footer, and the aria-label/`TOP_N=15` wording does not match.

- [ ] **Step 3: Rewrite the component body and imports**

In `frontend/src/components/metrics/FeatureImportance.tsx`:

(a) Update the React/recharts imports at the top of the file:

```tsx
import { useMemo, useState } from 'react'
import { BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
```

(b) Replace the **entire** `export function FeatureImportance(...) { ... }` body (everything from `export function FeatureImportance` to its closing brace) with:

```tsx
export function FeatureImportance({ features, title = 'Feature Importance' }: FeatureImportanceProps) {
  const { active, hoverProps } = useChartHover()
  const [expanded, setExpanded] = useState(false)

  const { charted, unusedCount, total } = useMemo(() => buildFeatureImportanceModel(features), [features])
  const hasOverflow = total > TOP_N
  const shown = useMemo(() => selectShownBars(charted, expanded), [charted, expanded])
  const realShown = shown.filter((d) => !d.isOther)

  const top3 = charted
    .slice(0, 3)
    .map((d) => `${d.name} ${(d.importance * 100).toFixed(1)}%`)
    .join(', ')
  const ariaLabel =
    expanded || !hasOverflow
      ? `Bar chart of all ${total} grouped features by importance: ${top3}`
      : `Bar chart of the top ${TOP_N} grouped features by importance, plus an Other bar aggregating ${total - TOP_N} more features: ${top3}`

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">{title}</CardTitle>
        <p className="mt-1 text-xs text-muted-foreground">
          Relative contribution of each feature across all of the model&apos;s decisions (normalised
          tree-based importance — split gain for gradient-boosted trees, impurity reduction for
          random forests). Magnitude only — it shows how much, not which way; for the direction a
          feature pushed a specific decision, see that application&apos;s explanation.
        </p>
      </CardHeader>
      <CardContent>
        <ul className="sr-only" aria-label="Feature importance list">
          {realShown.map((d) => (
            <li key={d.name}>{d.name}</li>
          ))}
        </ul>
        <div role="img" aria-label={ariaLabel}>
          <ResponsiveContainer width="100%" height={Math.max(280, shown.length * 36)}>
            <BarChart data={shown} layout="vertical" margin={{ top: 5, right: 30, bottom: 5, left: 10 }} {...hoverProps}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.4} horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }} />
              <YAxis
                dataKey="name"
                type="category"
                tick={{ fontSize: 11 }}
                width={160}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip content={renderEmptyTooltip} />
              <Bar dataKey="importance" name="Importance" radius={[0, 4, 4, 0]}>
                {shown.map((d) => (
                  <Cell key={d.name} fill={d.isOther ? 'hsl(var(--muted-foreground))' : 'hsl(var(--primary))'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <ChartHoverPanel active={active} formatValue={(v) => `${(Number(v) * 100).toFixed(1)}%`} />
        {hasOverflow && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mx-auto mt-2 block text-xs font-medium text-primary hover:underline"
          >
            {expanded ? 'Show fewer' : `Show all ${total} features`}
          </button>
        )}
        {unusedCount > 0 && (
          <p className="mt-2 text-center text-xs text-muted-foreground">
            {unusedCount} feature{unusedCount === 1 ? '' : 's'} had no measurable contribution (never
            used in a model split) and {unusedCount === 1 ? 'is' : 'are'} omitted.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
```

This removes the old inline `data` construction, the `TOP_N = 15`/`slice(0, 15)`/`hiddenCount` logic, and the old `+N more features not shown` footer (replaced by the Other bar + the unused-feature footer).

- [ ] **Step 4: Run the full file's tests to verify they pass**

Run (from `frontend/`):
```
npx vitest run src/__tests__/components/metrics/FeatureImportance.test.tsx
```
Expected: PASS — all logic tests AND all `<FeatureImportance />` render tests green.

- [ ] **Step 5: Commit**

```
git add frontend/src/components/metrics/FeatureImportance.tsx frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx
git commit -m "feat(metrics): grouped feature-importance chart with Other rollup, toggle, honest caption"
```

---

## Task 3: Verify lint, types, and the broader test suite

No new code — confirm the change is clean and nothing else references the removed behaviour.

**Files:** none (verification only)

- [ ] **Step 1: Lint the changed component**

Run (from `frontend/`):
```
npx eslint src/components/metrics/FeatureImportance.tsx src/__tests__/components/metrics/FeatureImportance.test.tsx
```
Expected: no errors. (If `react/no-unescaped-entities` fires, confirm apostrophes in the caption use `&apos;` as written.)

- [ ] **Step 2: Type-check**

Run (from `frontend/`):
```
npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Confirm no other test asserts the old chart behaviour**

Run (from `frontend/`):
```
npx vitest run -t "feature importance"
npx vitest run src/__tests__/pages/ModelMetricsPage.test.tsx src/__tests__/hooks/useMetrics.test.tsx
```
Expected: PASS. These pages render the chart indirectly; confirm none assert the removed `+N more features not shown` text or the top-15 cap. If any do, update them to the new copy (the Other rollup / "Show all" toggle) and re-run.

- [ ] **Step 4: Full frontend test run**

Run (from `frontend/`):
```
npx vitest run
```
Expected: PASS (whole suite green).

- [ ] **Step 5: Commit any fixups (only if Step 3 required edits)**

```
git add -A
git commit -m "test(metrics): update chart consumers for grouped feature-importance copy"
```

---

## Notes for the executor

- **Recharts in jsdom:** the chart's SVG may not lay out in tests, so all assertions target deterministic DOM — the `sr-only` `<ul>`, the `role="img"` `aria-label`, the toggle `<button>`, and the footer `<p>` — never the rendered bars. Keep it that way.
- **Do not touch `FEATURE_LABELS`** (current lines 14–113). Its `state_*`/`industry_*`/etc. entries become inert once grouping is in place but are harmless and act as a fallback if a prefix ever diverges.
- **Keep it frontend-only.** No backend, no retrain, no API/type changes.
