# Model Metrics — Tabbed Redesign & Review

- **Date:** 2026-06-07
- **Status:** Approved (design)
- **Branch:** `feat/model-metrics-tabbed-redesign`
- **Topic owner:** Neville Zeng
- **Surface:** `frontend/src/app/dashboard/model-metrics/` + `frontend/src/components/metrics/` (+ small backend `metrics.py` numeric fixes)

## 1. Problem / motivation

The Model Metrics page (`page.tsx`, 357 lines) renders **9 charts + 8 KPI cards + a 35-row
metadata dump** in nine stacked sections, all at "level 1" importance. It is one monolithic
component doing four unrelated jobs — model management (train state machine), quality metrics,
fairness, and production drift monitoring. The result is dense and hard to scan, and it mixes
concerns that have different audiences and refresh cadences.

A senior review was performed (page, all 9 components, backend `metrics.py`, and the live
active-model values pulled from the DB). Findings:

### 1.1 Accuracy verdict — the numbers are sound
Live active model (XGBoost `v20260604_153118`): AUC 0.871, Accuracy 0.811, Precision 0.886,
Recall 0.765, F1 0.821, KS 0.642, Gini 0.742, ECE 0.034, Brier 0.137.

- Realistic for a credit model — **not** the "0.99 everything" data-leakage smell. Internally
  consistent (Gini = 2·AUC − 1 = 0.742 ✓).
- Provenance is sound: `training_metadata` shows a **temporal train/val/test split**
  (`train/val/test_quarters`, `overfitting_gap`, `cv_auc_*`). Displayed values are held-out
  test-set metrics, not inflated training scores.

### 1.2 Minor correctness nits (small, none fatal)
- **ECE** (`backend/.../services/metrics.py:102`) is an *unweighted* mean over bins; textbook ECE
  weights by bin population, so sparse bins are overcounted.
- **Calibration chart** uses `type="monotone"` (`CalibrationChart.tsx:52`) → splines a reliability
  diagram, faking smoothness. Should be straight segments + dots.
- **Dead line** in `compute_decile_analysis` — `y_prob[order]` is computed and discarded
  (`metrics.py:172`).
- **Confusion-matrix** cell colour scales to the global max (`ConfusionMatrix.tsx:20`), so on
  imbalanced data TN washes out the other three cells.
- **Feature Importance** renders *every* feature with non-zero importance (79 features; chart
  height ∝ count), producing an extremely tall chart. No top-N cap (`FeatureImportance.tsx:137`).

### 1.3 Information-architecture issues (the real problem)
- 357-line monolith, four concerns in one component.
- No progressive disclosure — everything shown at once.
- Redundancy: two separate drift cards for one idea; a raw 35-key metadata dump.
- Drift is a *monitoring* concern, not model quality.

## 2. Goals / non-goals

**Goals**
- Reorganise into a tabbed dashboard with progressive disclosure; nothing currently shown is lost.
- Decompose the monolith into focused, independently-testable components.
- Apply targeted visual polish and the small correctness fixes.
- Keep the existing 5 page tests green; add coverage for the new structure.

**Non-goals**
- No change to the metrics API, data shape, or the `useModelMetrics`/`useDriftReports` hooks.
- No change to model training, the ML pipeline, or stored metric values (the ECE fix affects only
  *future* trained models).
- No new charting library (reuse `recharts`); no new UI dependency (`ui/tabs.tsx` already exists and
  is already used in `model-card/page.tsx`).

## 3. Design

### 3.1 Information architecture

**Always visible (above the tabs):**
- **Model header** — algorithm name, version + `Active` badges, admin Train control (algorithm
  select + button), and the training state banners (progress / success / skipped / error).
  Behaviour unchanged; restyled. Stays top-level so the existing tests and the train flow are
  unaffected by tab state.
- **KPI strip** — the 5 classic metrics in a tight row, **AUC-ROC as the hero stat**: AUC-ROC,
  Accuracy, Precision, Recall, F1. (These five labels are asserted by existing tests, so they must
  remain outside the tabs.)

**Tabs** (default = Performance):

| Tab | Contents | Source |
|----|----|----|
| **Performance** | Confusion Matrix + ROC Curve (2-col); Feature Importance (top 15) | existing components |
| **Fairness** | `FairnessCard` per protected attribute (state / applicant_type / employment_type) | existing |
| **Calibration & Thresholds** | Calibration reliability diagram + Threshold sweep | existing |
| **Drift** | One consolidated drift panel: status badge + headline PSI + PSI-over-time trend + the four mini-stats (report date, #predictions, approval rate, mean probability). Replaces the two separate cards. Tab is hidden when there are no drift reports. | merge of `DriftOverview` + `DriftPsiChart` |
| **Diagnostics** | Curated training metadata (~6 keys: split strategy, train/test size, CV-AUC ± std, overfitting gap, training time, calibration method); the jargon scalars (Gini, KS, Brier, log-loss, ECE) as a compact stat list; the **Decile/Gains** chart (moved here as "advanced"); active threshold | curated from the 35-key dump + relocated Decile |

Mapping guarantee — every current element has a destination: KPI extras (Gini/KS/Brier) → Diagnostics
stat list; metadata dump → curated Diagnostics; Decile → Diagnostics; two drift cards → one Drift tab
panel. Nothing is dropped.

### 3.2 Component decomposition (system design)

`page.tsx` becomes a ~80-line orchestrator: data hooks, loading/error/no-model states, and the tab
shell. New components (under `src/components/metrics/`, with a `tabs/` subfolder; exact placement
finalised in the plan):

- `ModelHeader.tsx` — info badges + admin train control + state banners.
- `KpiStrip.tsx` — the 5-metric headline row (AUC hero).
- `tabs/PerformanceTab.tsx`
- `tabs/FairnessTab.tsx`
- `tabs/CalibrationThresholdsTab.tsx`
- `tabs/DriftTab.tsx` — renders one consolidated `DriftPanel`; the old `DriftOverview` +
  `DriftPsiChart` are merged into it (redundancy removed).
- `tabs/DiagnosticsTab.tsx` — curated metadata + scalar list + Decile chart.

Existing chart components (`ConfusionMatrix`, `ROCCurve`, `FeatureImportance`, `CalibrationChart`,
`ThresholdChart`, `DecileChart`, `FairnessCard`) are reused as-is, only regrouped and lightly
adjusted for the polish items below. `ShapWaterfall.tsx` is not used by this page and is untouched.

### 3.3 Visual polish
- AUC-ROC rendered as a hero stat (larger, primary colour) within the KPI strip.
- Consistent card and chart heights within each row; consistent section spacing.
- Feature Importance capped to top 15 with a `+N more` affordance.
- Confusion-matrix cell colour normalised so TN no longer washes out TP/FP/FN.
- Calibration rendered as straight segments + dots (drop `monotone` spline).
- Shared chart palette sourced from design tokens rather than ad-hoc hex where practical.

### 3.4 Correctness fixes
- **Frontend (bundled):** calibration straight-line; feature top-15 cap; confusion-matrix colour
  normalisation.
- **Backend (bundled, future-models only):** population-weighted ECE in
  `compute_calibration_data`; remove the dead `y_prob[order]` line in `compute_decile_analysis`.
  The current stored ECE value will not change until a model is retrained — this is expected.

## 4. Data / API
No change. Metrics: `GET /api/v1/ml/models/active/metrics/` via `useModelMetrics`. Drift:
`useDriftReports(6)`. Same response shapes consumed.

## 5. Testing
- Existing 5 `ModelMetricsPage.test.tsx` cases must stay green unchanged — header, the 5 KPI labels,
  the train button, training banner, and error/no-model states all remain top-level (outside tabs).
- Add: tab-switching tests (default Performance; switching reveals Fairness / Calibration /
  Diagnostics content); Drift tab hidden when no reports; component tests for `KpiStrip`,
  `DriftPanel`, and curated metadata.
- Backend: update/extend metric tests for weighted ECE.
- Lint/type: `ruff` (backend, host), `vitest run` + typecheck (frontend).

## 6. Scope / risk / reversibility
- Frontend-only except the two small backend numeric fixes.
- No API/data-shape changes; no new dependencies (`ui/tabs.tsx` already in repo and in use).
- Pure regrouping of proven components + curation; low blast radius, easy to revert.
- Lands as a single PR off `feat/model-metrics-tabbed-redesign` → review → merge (no direct master).

## 7. Out of scope / follow-ups
- Surfacing the rich-but-unshown backend analytics (WOE/IV scorecard, Expected Loss, adversarial
  validation, concentration risk, vintage curves) — could become a future "Scorecard" view.
- Moving Drift to its own route (the alternative "split routes" direction) if monitoring grows.
- `ShapWaterfall` integration on a per-customer explanation surface (already exists elsewhere).

## 8. Open questions
None — all design decisions resolved during brainstorming.
