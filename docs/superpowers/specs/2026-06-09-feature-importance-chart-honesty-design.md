# Feature Importance Chart — Honesty & Completeness Fix

**Date:** 2026-06-09
**Status:** Design — approved; self-review complete; pending user review
**Scope:** Frontend only (`FeatureImportance.tsx` + its test). No backend change, no retrain.

## Problem

The Feature Importance chart on the Model Metrics page (Performance tab) has two defects that make it feel uninformative:

1. **It hides most features.** `FeatureImportance.tsx` hard-caps the chart at the top 15
   features (`const TOP_N = 15; data.slice(0, TOP_N)`) and renders the remainder as a grey
   "+N more features not shown" line. The backend (`metrics/compute.py:feature_importance_data`)
   already returns *every* feature, so the truncation is purely a display choice. With ~60–90
   features after one-hot encoding, the user sees a small fraction.

2. **One-hot dilution makes categoricals invisible and the ranking noisy.** Categorical features
   are exploded into many dummy columns at train time (`state_nsw`, `state_vic`, … ×8;
   `industry_anzsic_*` ×15; `purpose_*` ×5; etc. — see `ModelTrainer.CATEGORICAL_COLS`). Each
   dummy carries a sliver of importance, so a concept like "State" never appears as one bar —
   it scatters across eight near-zero bars that fall below the top-15 cut. The chart ends up
   dominated by a handful of continuous features while genuinely-used categoricals disappear.

The result is the chart "doesn't tell you anything": it shows an arbitrary slice of fragmented
features with an unlabelled magnitude.

## Goals

- Surface **every feature the model actually uses**, and **disclose (never silently drop)** the
  rest. A feature with zero tree importance was never split on — charting it as a 0.0% bar adds
  noise — but the count of such unused features is shown explicitly so nothing disappears silently.
- **Collapse one-hot dummies into one bar per parent categorical**, so categoricals are visible
  and the ranking is stable.
- **Label what the number means** so the magnitude is interpretable, and set honest expectations
  (it is a global, magnitude-only measure; direction lives in the per-application explanation).

## Non-Goals (YAGNI)

- No model retrain. The fix operates on the metrics already stored in the active `ModelVersion`.
- No backend / API change. The API already returns the full feature list.
- No swap to SHAP global importance (that was an alternative the user declined for now).
- No signed/directional importance — tree gain has no sign; the caption says so explicitly.

## Why frontend-only (chosen approach)

The component already owns the `FEATURE_LABELS` map that defines how raw feature keys map to
display names, and the backend already returns the complete, normalised importance list. Doing the
grouping and display logic in `FeatureImportance.tsx` means: no retrain, no API-shape change, works
on the currently-deployed model's stored metrics, fully reversible (revert one commit), and a blast
radius of exactly one component plus its test. Backend grouping was considered and rejected: it
would change the stored-metrics shape, require a retrain or read-time shim to populate, and touch
more tests — all for a result only the frontend consumes.

## Design

### 1. Collapse one-hot dummies → parent features

Grouping runs on the **raw feature keys** (e.g. `state_nsw`), before any label prettifying, because
the backend emits raw column names.

Define the categorical prefixes (mirroring `ModelTrainer.CATEGORICAL_COLS`, each as `name + "_"`):

| Prefix | Parent label |
|---|---|
| `state_` | State |
| `industry_anzsic_` | Industry (ANZSIC) |
| `industry_risk_tier_` | Industry Risk Tier |
| `purpose_` | Loan Purpose |
| `home_ownership_` | Home Ownership |
| `employment_type_` | Employment Type |
| `applicant_type_` | Applicant Type |
| `savings_trend_3m_` | Savings Trend (3m) |

For each feature key, match it against these prefixes **longest-prefix-first** (robust even though
the current set has no nested collisions) and, if matched, accumulate its importance into the
parent bucket via **sum**. Summing is the correct aggregation: `feature_importances_` is normalised
to sum to 1.0 across all features, so the sum of a categorical's dummy shares is that categorical's
total share of model gain. Features that match no prefix (all numeric features) stay individual.

Guardrails to verify in implementation:
- Numeric features that merely *start with a categorical word* must NOT be captured. The match is
  against the full `name + "_"` prefix, so `employment_length` / `employment_stability` do not
  match `employment_type_`, and `savings_balance` / `savings_to_loan_ratio` do not match
  `savings_trend_3m_`. The test plan asserts this.

After grouping, prettify each remaining raw key for display via the existing `formatFeatureName`
(parent labels come from the table above; numeric keys from `FEATURE_LABELS`). Sort descending.

**Charted set vs unused set.** Define the **charted set** = grouped features whose (summed)
importance rounds above `0` — these get bars. The **unused set** = grouped features whose importance
rounds to `0.0000` (never used in any split; the backend rounds to 4 dp at `compute.py:75`, so
small-share dummies and whole low-signal categoricals can land here). The unused set is **not**
drawn (zero bars are noise) but its **count is disclosed** in the footer — this is what replaces the
old silent `> 0` drop and satisfies Goal #1.

**Aggregation caveat (rationale, not user-facing).** Summing normalised dummy gain is the standard,
defensible proxy for a categorical's total share of model gain. Note it is a *lower bound* relative
to a grouped-permutation measure, because gain splits across correlated dummies. This is acceptable
under the magnitude-only framing and is why the caption says "relative contribution," not "the"
importance.

### 2. Show all used features; disclose the rest

Let **M = size of the charted set** (grouped features with non-zero importance, defined above).
Replace the hard `slice(0, 15)` with:

- **Collapsed (default):** render the **top 20** of the charted set individually. If `M > 20`,
  append a single **"Other (N features)"** bar whose value is the **sum** of the remaining charted
  tail, where **N = M − 20 counted in grouped units** (parent categoricals + ungrouped numerics in
  the tail — *not* raw dummy columns). So if the tail contains a collapsed "Industry" parent, it
  counts as 1 toward N, not 15. The Other bar conserves the tail, so the chart accounts for the full
  non-zero importance mass (the per-bar values sum to ≈1.0 before 4-dp rounding — do not claim an
  exact 100%).
- **Expanded:** a **"Show all M features"** toggle renders every member of the charted set
  individually and drops the "Other" bar; toggling again collapses back. "All M" means all M of the
  charted set — it does **not** resurrect the zero-importance unused set (those stay omitted, but
  remain disclosed via the footer in both states). M is therefore the same number in the toggle
  label and the expanded row count.
- **Footer disclosure** (both states): if the unused set is non-empty, show
  *"U feature(s) had no measurable contribution (never used in a model split) and are omitted."*
  This is the explicit, non-silent accounting for Goal #1. The old "+N more features not shown"
  line is removed (the Other bar + this footer replace it).

Chart height continues to scale with the number of visible rows (`Math.max(280, rows * 36)`), so the
expanded view grows accordingly.

### 3. Make the number mean something

Add a one-line caption directly under the card title (small, muted):

> *Relative contribution of each feature across all of the model's decisions (normalised tree-based
> importance — split gain for gradient-boosted trees, impurity reduction for random forests).
> Magnitude only — it shows how much, not which way; for the direction a feature pushed a specific
> decision, see that application's explanation.*

This states it is (a) global, (b) normalised, (c) magnitude-only, and (d) points to the
per-application SHAP explanation that already exists in the decision view. The wording is
**algorithm-neutral** so it is correct whichever `ModelVersion` is active without the component
needing to know the algorithm — it names both the XGBoost (gain) and Random Forest (impurity)
interpretations, both of which are normalised, unsigned tree importances. (If we later want the
exact term shown conditionally, the algorithm would have to be threaded in as a prop — out of scope
here.)

### 4. Accessibility

The `sr-only` feature list and the `role="img"` `aria-label` must reflect the **grouped, currently
real-feature** set, never the raw dummies, and must exclude the synthetic "Other" bar from any
"top features" sample (it is not a feature). Specify both states:

- **Collapsed:** *"Bar chart of the top {K} grouped features by importance, plus an Other bar
  aggregating {N} more features: {top-3 real feature names with %}."* (`K` = min(20, M); top-3 are
  real features, never "Other".)
- **Expanded:** *"Bar chart of all {M} grouped features by importance: {top-3 real feature names
  with %}."*

The `sr-only` list enumerates the visible real features only (not the "Other" bar). The
`ChartHoverPanel` hover behaviour is unchanged (it operates on the `importance` value).

## Affected files

- `frontend/src/components/metrics/FeatureImportance.tsx` — grouping, rollup + expand toggle,
  caption, a11y label updates. Add a `CATEGORY_GROUPS` prefix→label map alongside `FEATURE_LABELS`.
- `frontend/src/__tests__/components/metrics/FeatureImportance.test.tsx` — rewrite the two existing
  top-15 tests (they assert behaviour this change removes) and add the cases below.

No other files. `PerformanceTab.tsx` passes `metrics.feature_importances` straight through and is
unaffected. The `ModelMetrics` / prediction types are unaffected (input shape unchanged).

## Test plan

Rewrite `FeatureImportance.test.tsx` to cover:

1. **Collapses dummies into one parent bar.** Feed `{state_nsw, state_vic, state_qld}` with known
   importances → assert a single "State" bar exists with the summed value, and no "State: NSW" bar.
2. **Numeric look-alikes are not captured.** Feed `employment_length` and `employment_type_payg_permanent`
   together → assert "Employment Length" stays its own bar and is not folded into "Employment Type".
3. **Tail rolls into an "Other" bar that conserves the tail.** Feed 25 numeric features → assert 20
   individual bars + an "Other (5 features)" bar whose value equals the sum of ranks 21–25.
4. **"Other" counts grouped units, not raw dummies.** Feed 20 numerics + a full collapsed categorical
   group (e.g. 8 `state_*` dummies) that lands in the tail → assert the categorical contributes **1**
   to N, i.e. "Other (1 feature)" (or the correct small count), never +8.
5. **No "Other" bar when M ≤ 20.** Feed 10 features → assert no "Other" text and no toggle.
6. **Expand toggle reveals the full charted set.** With M > 20, click "Show all M features" → a
   previously-hidden charted feature appears, the "Other" bar is gone, exactly M bars render;
   clicking again collapses back.
7. **Unused (zero-importance) features are disclosed, not charted.** Feed some features with
   importance `0` (including a categorical whose dummies are all `0`) → assert those bars are absent
   **and** the footer reads "U feature(s) had no measurable contribution … omitted" with the right U.
8. **Realistic mixed shape.** Feed several full categorical dummy groups + ~30 numerics (approximating
   the deployed model) → assert the post-collapse M exceeds 20 so the Other rollup and toggle are
   live (guards against the toggle being dead code on the real model).
9. **Caption is present** and names the metric (algorithm-neutral wording).
10. **Array input shape** (`Array<{feature, importance}>`) groups identically to the record shape.

Run: `npx vitest run` (per project convention; not `npm test`).

## Risks & rollback

- **Risk:** prefix list drifts from `CATEGORICAL_COLS` if the trainer adds a categorical later.
  *Mitigation:* the parent-label table is the single place to update, and an unmatched categorical
  simply renders as individual dummy bars (degrades gracefully, not silently wrong). Out of scope to
  auto-sync, but noted in a code comment pointing at `ModelTrainer.CATEGORICAL_COLS`.
- **Risk:** none to data — pure presentation change on already-computed metrics.
- **Rollback:** revert the single commit. No migration, no model artifact change.

## Open items

None blocking. The XGBoost `feature_importances_` semantics (normalised gain for gbtree in
xgboost 3.2.0) are confirmed against the pinned version. Resolved during spec review:
zero-importance features are disclosed via a footer count rather than silently dropped; "Other (N)"
counts grouped units; the caption is algorithm-neutral; the realistic-shape test guards the toggle
against being dead code on the deployed model.
