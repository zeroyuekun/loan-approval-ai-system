# Model Metrics — Lender-Replica Redesign

**Status:** Drafted, awaiting user review
**Owner:** Neville
**Date:** 2026-05-08
**Branch (proposed):** `feat/model-metrics-lender-replica`
**Audience:** Lending analyst (primary) — based on user's stated preference for an aggressive cut

---

## Background

`/dashboard/model-metrics` has accreted ten panels over many feature commits. The recently-shipped `<ModelCard />` (commits `bd12f10`–`ad0cba6`) duplicates roughly 70% of what the rest of the page already renders. A separate orphan route at `/dashboard/model-card` (introduced in v1.7.0, never wired into the sidebar) further duplicates the same surface.

The user asked for a redesign that mirrors what real loan-lending platforms show analysts, with aggressive removal of dead code.

## Goals

1. Replace the current 10-panel page with a layout that mirrors lender monitoring dashboards (CreditVigil-style: KPI strip → discrimination + governance → calibration + decile → stability → fairness).
2. Remove redundant visual components without losing any underlying data signal — every metric currently rendered must remain visible somewhere.
3. Delete the orphaned `/dashboard/model-card` route and its hook/test fixtures.
4. Keep the backend untouched — frontend cleanup only.

## Non-goals

- Backend changes (the `/ml/models/active/model-card/` endpoint, MRM dossier, DriftReport schema all stay as-is).
- Adding new data signals that require backend support (e.g. Gini/KS trend over time would require storing those at each DriftReport — out of scope).
- Touching `/dashboard/applications` or `ApplicationDetail.tsx` — `ShapWaterfall` and `FeatureImportance` are still consumed there.

## Industry research (synthesis)

Cross-referenced six analyst-focused sources:

- [CreditVigil](https://creditvigil.com/) — independent credit model monitoring (most analyst-focused public reference)
- [DMS Anolytics — Monitoring Borrower Data](https://www.dms.net/wp-content/uploads/2025/09/Monitoring-Borrower-Data-Advanced-Monitoring.pdf)
- [LinkedIn Shailendra — Credit Risk Scorecard Monitoring](https://www.linkedin.com/pulse/credit-risk-scorecard-monitoring-tracking-shailendra)
- [Anolytics Medium — How to evaluate and monitor AI models for financial risk](https://medium.com/anolytics/how-to-evaluate-and-monitor-performance-of-ai-models-for-financial-risk-management-a-practical-b600d50140cb)
- [Zest AI Lending Intelligence](https://www.zest.ai/product/lending-intelligence/)
- [GiniMachine — ML Model Performance Evaluation](https://ginimachine.com/academia-post/ml-model-performance-evaluation/)

**Convergent pattern across all six:**

| Tier | What | Why |
|---|---|---|
| KPI strip | AUC/Gini · KS · PSI · Approval rate, each with traffic-light band | "Is the model working today?" |
| Discrimination + governance | Headline metrics, drivers, scope, posture | What/why summary |
| Calibration | Reliability diagram + ECE | Are probabilities trustworthy? |
| Decile / Lift | Rank-order quality across deciles | Is risk concentrated correctly? |
| Stability | PSI alert + trend over time | Has the population shifted? |
| Fairness | DI per protected attribute, 4/5ths rule | Treating groups consistently? |

**Notably absent from every source:** confusion-matrix tiles, full ROC curves, threshold-sweep multi-line plots, generic accuracy %, raw training metadata KV. These are model-development tools, not monitoring tools.

## Final layout

```
Header: algorithm · v1.x · Active   [Train New ▾]
[Train banner — when active only]

┌─ KPI Strip (4 tiles, lender-style traffic-light) ────────┐
│  AUC 0.87 ✓  │  KS 0.51 ✓  │  PSI 0.06 ✓  │  Approval 42% │
│  >0.75 green │  >0.30 green│  <0.10 stable│  delta vs prev│
└──────────────────────────────────────────────────────────┘

┌─ ModelCard (existing — expanded) ────────────────────────┐
│  Performance: AUC · KS · Gini · ECE · Brier              │
│               + Train/test gap · Lift over LR baseline   │
│               + Confusion P · R · n                       │
│  Decision thresholds: Active · F1-optimal · Cost-optimal │
│  Top drivers (3 inline + "Show all features ▾" toggle)   │
│  Trained on AU sources                                   │
│  Not validated for                                       │
│  Production posture                                      │
│  ▸ Show raw training metadata                            │
└──────────────────────────────────────────────────────────┘

┌─ Calibration ──────────────┬─ Decile / Lift ─────────────┐
│ reliability diagram + ECE  │ rank-order quality          │
└────────────────────────────┴─────────────────────────────┘

┌─ Stability summary ────────┬─ Drift trend ───────────────┐
│ alert level + PSI score    │ PSI + approval rate dual-line│
└────────────────────────────┴─────────────────────────────┘

┌─ Fairness — DI per protected attribute (4/5ths rule) ────┐
└──────────────────────────────────────────────────────────┘
```

## Component plan

### New

| File | Purpose |
|---|---|
| `frontend/src/components/metrics/KpiStrip.tsx` | 4-tile lender-style headline with traffic-light bands. Tile shape: `{ label, value, threshold, band: 'green'\|'amber'\|'red', delta? }`. Uses thresholds from `lib/benchmarks.ts`. |

### Edited

| File | Change |
|---|---|
| `frontend/src/components/metrics/ModelCard.tsx` | Performance section gains 3 new rows: train/test gap (from ModelHealthCard), lift over LR baseline (from ModelHealthCard), confusion P/R/n (derived from `metrics.confusion_matrix`). New "Decision thresholds" subsection. Top drivers gains a `Show all features ▾` toggle that renders `<FeatureImportance />` inline. New collapsed `<details>` footer for raw `training_metadata` (lifted from ModelHealthCard's `RawMetadataTable`). |
| `frontend/src/components/metrics/DriftPsiChart.tsx` | Renamed → `DriftTrendChart.tsx`. Adds a second line series for approval rate over reports, dual-axis. |
| `frontend/src/components/metrics/DriftOverview.tsx` | Title changed from "Drift Status" → "Stability". |
| `frontend/src/app/dashboard/model-metrics/page.tsx` | Remove deleted imports + panels. Compose new layout: header → train banner → KpiStrip → ModelCard → (Calibration + Decile) → (Stability + DriftTrend) → Fairness. |
| `frontend/src/lib/api.ts` | Remove `mlApi.getModelCard`. |
| `frontend/src/types/index.ts` | Remove `ModelCard` interface (the API-shaped one — distinct from the component). |
| `frontend/src/test/mocks/handlers.ts` | Remove handler for `/ml/models/active/model-card/`. |

### Deleted

| File | Reason |
|---|---|
| `frontend/src/components/metrics/ConfusionMatrix.tsx` | Chart; signals migrate to ModelCard P/R/n row + KPI strip. |
| `frontend/src/components/metrics/ROCCurve.tsx` | Chart; AUC stays as KPI strip + ModelCard row. |
| `frontend/src/components/metrics/ThresholdChart.tsx` | Chart; F1/Youden/Cost-optimal stay as one-liner in ModelCard. |
| `frontend/src/components/metrics/ModelHealthCard.tsx` | All 6 dimensions absorb into ModelCard. Raw metadata KV becomes ModelCard's collapsed footer. |
| `frontend/src/app/dashboard/model-card/page.tsx` | Orphan route — never linked from sidebar. The new in-page `ModelCard` replaces it. |
| `frontend/src/hooks/useModelCard.ts` | Only consumer was the orphan page. |
| `frontend/src/__tests__/pages/ModelCardPage.test.tsx` | Page deleted. |
| `frontend/src/__tests__/hooks/useModelCard.test.tsx` | Hook deleted. |

### Kept (no change)

- `FeatureImportance.tsx` — still consumed by `ApplicationDetail.tsx`; will also be used inline by ModelCard's "Show all features" toggle.
- `ShapWaterfall.tsx` — still consumed by `ApplicationDetail.tsx`.
- `FairnessCard.tsx`, `DecileChart.tsx`, `CalibrationChart.tsx` — kept as-is.
- All backend code: `getModelCard` view, `test_model_card.py`, MRM dossier, DriftReport model.

## Signal migration matrix (audit trail)

Every signal currently shown on `/dashboard/model-metrics` has a destination. Nothing is silently dropped.

| Signal source | Today | After |
|---|---|---|
| Accuracy, Precision, Recall, F1 | 8-tile grid | ModelCard Performance section (compact rows) |
| AUC-ROC | 8-tile grid + ROCCurve + ModelCard | KPI strip + ModelCard |
| Gini, KS, Brier | 8-tile grid + ModelHealthCard | KPI strip (KS) + ModelCard Performance rows |
| Confusion matrix counts | ConfusionMatrix card | ModelCard "Confusion: P 0.71 · R 0.69 · n 50,000" row |
| ROC curve points | ROCCurve | Removed (the AUC summary number is the analyst signal) |
| Calibration buckets | CalibrationChart | CalibrationChart (kept) |
| ECE | CalibrationChart + ModelHealthCard + ModelCard | ModelCard Performance row + CalibrationChart caption |
| Threshold sweep | ThresholdChart | Removed visual; F1/Youden/Cost-optimal numbers stay as one-liner in ModelCard |
| Optimal threshold (active) | ThresholdChart + ModelHealthCard raw | ModelCard "Decision thresholds" row |
| Top features (full ranking) | FeatureImportance | ModelCard "Show all features ▾" toggle (renders FeatureImportance inline) |
| Top 3 drivers | ModelCard | ModelCard (unchanged) |
| Train/test gap | ModelHealthCard | ModelCard Performance row |
| Lift over LR baseline | ModelHealthCard | ModelCard Performance row |
| PSI per feature | ModelHealthCard | ModelCard raw-metadata footer (full map) |
| Governance gates | ModelHealthCard | ModelCard raw-metadata footer (full decision JSON) |
| Raw `training_metadata` | ModelHealthCard collapsed | ModelCard collapsed footer |
| Decile analysis | DecileChart | DecileChart (kept) |
| Drift overview / alert level | DriftOverview | DriftOverview (renamed "Stability") |
| PSI score over time | DriftPsiChart | DriftTrendChart (now with approval-rate too) |
| Approval rate over time | _not currently visualized_ | DriftTrendChart second series — **net new signal** |
| Fairness DI per attribute | FairnessCard | FairnessCard (kept) |
| ModelCard intended_use, training_data, governance, validation, regulatory_compliance | `/dashboard/model-card` orphan route | Backend endpoint stays; frontend route gone. Reachable via API call or future re-add. |

## Test plan

- Update `frontend/src/__tests__/pages/ModelMetricsPage.test.tsx` (if exists) for new layout.
- Update `frontend/src/__tests__/components/ModelCard.test.tsx` for new sections (gap, lift, confusion row, decision thresholds, show-all-features toggle, raw metadata footer).
- New unit test for `KpiStrip.tsx` covering all 4 tile bands + missing-data fallback.
- Delete tests for deleted components (`ConfusionMatrix`, `ROCCurve`, `ThresholdChart`, `ModelHealthCard`) if they exist.
- Delete `__tests__/pages/ModelCardPage.test.tsx` and `__tests__/hooks/useModelCard.test.tsx`.
- E2E smoke (Playwright if used in this repo, else manual): load `/dashboard/model-metrics` with active model, confirm KPI strip + ModelCard render; load with no active model, confirm empty state; load `/dashboard/model-card` confirms 404 (route gone).

## Migration / risk

- **Risk:** someone deep-links to `/dashboard/model-card`. **Mitigation:** there's no link to it in the sidebar today, no documentation references it; deletion will return Next.js's standard 404. Acceptable per the user's "aggressive cut" preference.
- **Risk:** removing the orphan-page test fixtures breaks the test suite. **Mitigation:** delete the test files in the same commit that deletes the page/hook.
- **Risk:** ModelCard becomes too long with all the absorbed signals. **Mitigation:** hide raw metadata behind collapse, hide full feature importance behind toggle. Performance section grows from 3 rows to ~8 rows of text — still scannable.
- **Risk:** existing screenshot tests / Playwright snapshots break. **Mitigation:** regenerate as part of the implementation phase.

## Build sequence (handoff to gsd)

Three atomic commits, each independently revertable:

1. **`feat(metrics): KPI strip + ModelCard expansion`** — adds `KpiStrip.tsx`, expands `ModelCard.tsx` with migrated rows + toggle + footer. ModelCard tests updated. No deletions yet.
2. **`refactor(metrics): drop redundant chart panels from model-metrics page`** — `model-metrics/page.tsx` removes ConfusionMatrix/ROC/Threshold/ModelHealthCard/8-tile imports + panels. Deletes those four `.tsx` files. Renames `DriftPsiChart` → `DriftTrendChart`, adds approval-rate series. `DriftOverview` title change.
3. **`chore(metrics): delete orphan /dashboard/model-card route + dead code`** — deletes `app/dashboard/model-card/page.tsx`, `hooks/useModelCard.ts`, `mlApi.getModelCard`, `ModelCard` interface in `types/`, MSW handler, and the two related test files.

Each commit lands cleanly with passing tests before moving to the next.

## Open questions for review

None — design is complete. The user's pre-existing trust-delegation memory + auto mode + explicit "replicate other lending platforms" directive cover the design choices.
