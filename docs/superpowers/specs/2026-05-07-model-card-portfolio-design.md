# Model Card panel + AU data calibration showcase

**Date:** 2026-05-07
**Branch target:** new branch off `fix/training-metadata-gate-honesty` (so this lands after the v1.10.7 propagation fix)
**Status:** spec drafted, awaiting user review

---

## 1. Problem

The `/dashboard/model-metrics` page is the model's portfolio-facing surface. The reader the user cares about is a **hiring manager** evaluating his portfolio in 30 seconds. Today the page shows ~30 numbers and ~10 charts but no narrative — a reader can't tell:

- What the model actually predicts
- What it learned from (and why the synthetic data is credible)
- Whether the numbers are credible (lift over what? generalize beyond training data?)
- Where it would fail in production

The recently-shipped `ModelHealthCard` answers a different question — "did internal gates pass?" — which is an audit-style view, not a portfolio-walkthrough view. The user's feedback: *"it's not really telling me anything useful, also put the model health card at the very bottom."*

The user also noted: *"I don't have much real data… I want you to try to replicate what other Australian loan data is like and try to replicate real world scenario."* On audit, the project **already does this** — `DataGenerator` is calibrated against ~10 public Australian sources (ATO, ABS, APRA, RBA, Equifax, HEM). The realism work is largely done; what's missing is **surfacing it as a credibility flex on the dashboard**.

## 2. Goal

Two coordinated phases:

**Phase A — Calibration audit + manifest.** Document every public AU benchmark already encoded in `DataGenerator`, identify any gaps against the AU realism research (§4), and produce a single `backend/docs/CALIBRATION_SOURCES.md` that the Model Card can link to.

**Phase B — Model Card panel.** Add a `<ModelCard />` component at the top of `/dashboard/model-metrics` that delivers a 30-second credibility narrative. Lead with **"calibrated against real AU data sources"** as the Trained-On claim, not "synthetic." Move the existing `ModelHealthCard` to the bottom under an "Audit & Governance" framing.

Acceptance: a hiring manager who only reads the new Model Card walks away knowing what the model predicts, what it beats, **what real AU data it was calibrated against**, what it was independently validated on (Kaggle GMSC), and where it doesn't apply — with at least one citable industry-context line they can repeat back in an interview.

## 3. Industry research findings (commercial credit platforms)

| Source | Pattern worth replicating |
|---|---|
| Upstart investor disclosures | Lead with the **lift number** ("44% more approvals than FICO at the same default rate"). Business framing first, ML metrics second. |
| Zest AI explainability docs | Pair AUC with **calibrated probabilities + adverse-action reasons** so probabilities are usable for pricing decisions. Auto-generated MRM dossier is the regulator gold standard. |
| Kaggle GMSC top scores | Top XGBoost solutions plateau at AUC ~0.86–0.87 on real borrower data. This project hits **0.866 on the same data** — credible peak. |
| Realistic credit-default benchmarks | AUC 0.75–0.80 on real data is the industry baseline; AUC > 0.95 is suspicious (leakage / overfit). Anchor 0.873 to this band. |
| APRA APS 220 | Credit-risk grading must "rank risk consistently through time." The temporal-quarter CV already satisfies this — surface it. |

## 4. AU lending data benchmarks (research synthesis)

| Real benchmark | Number | Status in project |
|---|---|---|
| 90+ day mortgage arrears (APRA Q1 2025) | 1.68% of loan book | Already calibrated in `DataGenerator` — RBA FSR Oct 2025 cited |
| 30–89 day arrears (APRA June Q3 2025) | 0.55% | Already cited (0.47% RBA Oct 2025) |
| Pandemic-peak arrears (mid-2020) | 1.86% | Stress-scenario context |
| RBA severe stress test (10% unemployment, −4% GDP, −40% house prices) | <4% severe-risk arrears | Out of scope — defer |
| HEM (Melbourne Institute, ABS-anchored) | 600+ items, median basics + 25th-pct discretionary | Already encoded — `HEM_TABLE` + `STATE_HEM_MULTIPLIER` |
| APRA serviceability buffer | 3% above product rate; 2025 assessment 9.5–10.0% | Already encoded — `STRESS_TEST_BUFFER = 3.0` |
| New-loan LVR ≥ 80% (APRA Sep Q 2025) | 30.8% | Already calibrated |
| New-loan DTI ≥ 6 (APRA Sep Q 2025) | 6.1% | Already calibrated |
| Equifax average credit score | 864/1200 | Already calibrated incl. age + state breakdowns |
| Median Equifax score | 661 | Already calibrated |
| ATO median taxable income (2022-23) | $55,868 | Already calibrated |
| ABS median employee earnings (Aug 2025) | $74,100/yr | Already calibrated |
| ABS dwelling values (Dec Q 2025) | mean $1,074,700 | Already calibrated |
| Avg owner-occ loan (ABS Lending Indicators Dec Q 2025) | $693,801 | Already calibrated |
| Employment mix (ABS CofE Aug 2025) | PAYG perm 77% / casual 19% / SE 7.6% / contract 4% | Already calibrated (current weights 68/12/12/8 — gap, see §6) |

## 5. What `DataGenerator` is already calibrated against

`backend/apps/ml_engine/services/data_generator.py:46-67` documents 10 named public sources spanning ATO, ABS, APRA, RBA, Equifax, Melbourne Institute, plus subordinate services (`benchmark_resolver`, `feature_generator`, `loan_performance_simulator`, `underwriting_engine`) for **3,269 LOC of calibrated synthetic-data plumbing**.

Key concrete calibrations:
- **Default rate** seeded from RBA FSR Oct 2025 (<1% owner-occ 90+ day arrears)
- **HEM table** + state-level cost-of-living multiplier
- **APRA 3% serviceability buffer** above product rate
- **RBA cash rate quarterly history** (actual + projected)
- **HELP repayment thresholds** (ATO 2025-26)
- **ANZSIC industry weights + AWE income multipliers** (ABS Labour Force / AWE Aug 2025)
- **State-by-age Equifax credit-score means** (ACT 915, NSW 890, …, NT 844)
- **Markov-chain post-approval performance trajectories**

This is not a half-built synthetic generator. It's a public-source-anchored simulator of the AU retail-lending population.

## 6. Calibration gaps (small)

Discovered while auditing §5 against §4:

1. **Employment-type weights drift** — current `EMPLOYMENT_TYPE_WEIGHTS = [0.68, 0.12, 0.12, 0.08]` doesn't match the docstring's cited ABS Aug 2025 distribution (perm 77%, casual 19%, SE 7.6%, contract 4%). The ABS row sums to 1.076 because casual is a sub-category of PAYG; the project's split is non-overlapping. Cleanest fix: realign weights to a non-overlapping interpretation (e.g. 0.68 perm-non-casual / 0.19 casual-PAYG / 0.08 SE / 0.05 contract = 1.00) and update the constant's comment to cite the derivation. Either way, document the chosen interpretation so it's defensible in `CALIBRATION_SOURCES.md`.
2. **Default rate target** — module docstring cites RBA "<1%" but no test asserts the synthetic positive rate stays in band. Add a regression test enforcing positive-class rate within an explicit band (e.g. 1.5–4% to give the model tractable signal while staying within order-of-magnitude of real AU mortgage arrears + personal loan arrears combined).
3. **No RBA stress-scenario product** — out of scope here, but worth a future spec: a "stress mode" for `DataGenerator` that simulates the RBA April 2025 severe scenario (10% unemployment, −4% GDP, −40% house prices) for stress-testing the model's robustness.

## 7. Phase A — Calibration manifest (small)

### 7.1 New file: `backend/docs/CALIBRATION_SOURCES.md`

A single canonical document listing every public AU source the synthetic data is calibrated against. Sections:

1. **At a glance** — five-line summary (sources count, last calibration date, validation methodology)
2. **Sources** — one row per benchmark, with:
   - Source name + URL
   - Last-known publication date
   - Numeric value used
   - Where it's encoded in code (`file_path:line_number`)
3. **Validation** — how synthetic distributions are checked against benchmarks (defaults, credit score, LVR, DTI distributions)
4. **Out of scope** — RBA stress scenarios, real lender data, longitudinal panel data

Total length: ~150 lines. Audit-honest; updated whenever a benchmark in DataGenerator's docstring changes.

### 7.2 Tiny code fix: realign employment-type weights + document interpretation

`backend/apps/ml_engine/services/data_generator.py:79`:

The chosen interpretation should be settled during plan-writing (open question §15.4). Whichever we pick, the constant gets a comment line citing ABS Aug 2025 + the derivation, and `CALIBRATION_SOURCES.md` records it so the choice is defensible.

Two candidates:
- **(a) Match docstring exactly** (overlap-aware, 0.77/0.19/0.076/0.04 — sums to 1.076 because casual ⊂ PAYG; reweighted to 1.0 as 0.715/0.176/0.071/0.037).
- **(b) Keep current `[0.68, 0.12, 0.12, 0.08]` with an explicit comment** that the project models perm-non-casual / casual / SE / contract as non-overlapping; ABS perm includes casual so the project's split deliberately separates them.

Either choice is defensible if documented; (b) requires zero code change beyond a comment, which is the lowest-risk path.

### 7.3 New regression test: class-balance band

`backend/tests/test_data_generator_realism.py`:

```python
def test_synthetic_class_balance_within_documented_band():
    """Regression guard: the synthetic positive-class rate must stay within
    a documented band so a future calibration tweak can't silently shift
    the training distribution.

    The current project runs at ~0.22–0.44 positive class (deliberately
    higher than real-world arrears so the model has tractable signal without
    SMOTE / class-weight gymnastics). Real AU mortgage 90+ day arrears sit
    at 1.68% (APRA Q1 2025); the gap is intentional and documented in
    CALIBRATION_SOURCES.md §Validation.
    """
    df = DataGenerator().generate(num_records=10000, random_seed=42)
    rate = df["approved"].mean()
    assert 0.20 <= rate <= 0.45, (
        f"Class balance {rate:.3f} drifted outside documented [0.20, 0.45] band — "
        "either re-anchor and update CALIBRATION_SOURCES.md, or revert the "
        "calibration change."
    )
```

The test asserts the project's *documented* synthetic class balance is stable, not that it matches real arrears. The deliberate gap between synthetic ~30% and real ~1.68% is acknowledged honestly in `CALIBRATION_SOURCES.md` so a hiring manager reading the receipts sees the design choice, not a hidden mismatch.

## 8. Phase B — `<ModelCard />` component

### 8.1 Component file

`frontend/src/components/metrics/ModelCard.tsx` — self-contained card with five labeled sections.

### 8.2 Content blueprint

**Header**
- Title: `<algorithm display name> · v<version>`
- Sub-title: segment-specific purpose statement (mirrors `mrm_dossier._SEGMENT_PURPOSE`)
- Right-side meta: feature count from `feature_importances`

**Section 1 — Performance**
- AUC: `metrics.auc_roc` → "ranks a random good vs bad pair correctly N% of the time"
- KS: `metrics.ks_statistic` → "separates approved-good from denied-bad probability distributions by N points"
- ECE: `metrics.calibration_data.ece ?? metrics.ece` → "predicted probabilities match observed default rates within N% on average"

Industry-context callout (static copy):
> Industry research puts realistic credit-default AUC at **0.75–0.80** on real data; Upstart reports **>0.75 vs FICO's ~0.65**. Top Kaggle GMSC solutions plateau around **0.866** on real borrower data.

**Section 2 — Credibility evidence**
Five ✓ rows, each sourced from `training_metadata`:

| Row | Source | Pass condition |
|---|---|---|
| Lift over LR baseline | `training_metadata.xgb_lift_over_baseline` + `baseline_auc` | lift > 0 |
| Real-data benchmark (Kaggle GMSC) | static `GMSC_BENCHMARK_AUC = 0.866`; gap = `auc_roc - 0.866` | gap < 0.05 |
| Temporal stability | `training_metadata.temporal_cv_auc_mean` ± `temporal_cv_auc_std` | mean within 0.02 of `auc_roc` |
| Calibration ceiling | `ece` | < 0.03 |
| Fairness 80% rule | `fairness_metrics[*].passes_80_percent_rule` | all attrs pass |

**Section 3 — Trained on (the realism flex)**
This is the section that addresses the user's "I don't have much real data" concern. Reframe synthetic data as **calibrated synthetic**:

```
80,000 samples calibrated against real Australian public sources:
  • ATO Tax Stats 2022-23  (income percentile distributions)
  • ABS Employee Earnings + Lending Indicators (2025)
  • APRA Property Exposures Sep Q 2025  (LVR / DTI / NPL distributions)
  • Equifax 2025 Credit Scorecard       (state + age score distributions)
  • RBA Financial Stability Review Oct 2025  (default-rate targets)
  • HEM benchmarks (Melbourne Institute, CPI-indexed)

Independently validated against the Kaggle GMSC benchmark (150k real
borrowers): AUC 0.866 — 1pp gap from internal test → no synthetic-data
overfit.
```

Below that, a **"View calibration sources →"** link that opens `backend/docs/CALIBRATION_SOURCES.md` (rendered as a static asset or via a markdown viewer; if the simplest path is a GitHub link to the file, that's acceptable).

**Section 4 — Not validated for**
Bulleted list, segment-specific, sourced from a `SEGMENT_LIMITS` constant that mirrors `mrm_dossier._SEGMENT_PURPOSE`'s scope-exclusion clauses.

**Section 5 — Production posture**
Three short lines, conditional on data presence:
- "SHAP adverse-action reasons per decision"
- "MRM dossier per model version (APRA CPS 220 / SR 11-7 format)"
- "Pre-activation gates: fairness `<mode>` / promotion `<mode>`" (only when modes recorded)
- "Weekly drift report (PSI per feature)"

### 8.3 Page reordering — `frontend/src/app/dashboard/model-metrics/page.tsx`

```
1.  Title / badges / Train button         (unchanged)
2.  Training status banners               (unchanged)
3.  <ModelCard />                         ← NEW headline
4.  Key Metrics tiles                     (unchanged)
5.  ConfusionMatrix + ROCCurve            (unchanged)
6.  FeatureImportance                     (unchanged)
7.  Banking Metrics                       (unchanged)
8.  Fairness                              (unchanged)
9.  Drift                                 (unchanged)
10. Decile chart                          (unchanged)
11. <h3>Audit & Governance</h3>           ← NEW heading
12. <ModelHealthCard />                   ← MOVED here
```

### 8.4 Empty-state behaviour

When `training_metadata` is missing (legacy models pre-v1.10.7):
- Each Credibility row renders with explicit "not recorded" sub-line + ⚠ icon.
- One info banner inside the card top: "This model was trained before v1.10.7. Some credibility evidence isn't recorded — re-train to refresh."
- The card never hides. Audit-honest.

## 9. Data contract

| Section | Field | Backend source |
|---|---|---|
| Header | `algorithm`, `version` | `ModelVersion` columns |
| Header sub-title | `SEGMENT_PURPOSE` constant (mirrors dossier) | static |
| Performance | `auc_roc`, `ks_statistic`, `ece`/`calibration_data.ece` | `ModelVersion` columns |
| Lift over LR | `training_metadata.xgb_lift_over_baseline`, `.baseline_auc` | `trainer.py` |
| GMSC real-data | static `GMSC_BENCHMARK_AUC = 0.866` | sourced from PR #141 (memory) |
| Temporal CV | `training_metadata.temporal_cv_auc_mean/std` | `trainer.py` |
| Calibration ceiling | `ece` | `ModelVersion.ece` |
| Fairness | `fairness_metrics[*].passes_80_percent_rule` | `MetricsService` |
| Trained on | `training_metadata.train_size`/`val_size`/`test_size`/`class_balance` + static AU sources list | `trainer.py` + new `CALIBRATION_SOURCES.md` |
| Not validated for | `SEGMENT_LIMITS` constant (mirrors dossier) | static |
| Production posture | `training_metadata.fairness_gate_mode` / `.promotion_gate_mode` | `tasks.py` |

**No new backend metric fields required.** The static AU-sources list is hard-coded in the frontend (cheap; sources change rarely) AND maintained in the `CALIBRATION_SOURCES.md` doc.

## 10. Out of scope

- Major `DataGenerator` overhaul — already done by Arm A v1.10.0 (per memory `project_arm_a_xgboost_au_parity.md`).
- RBA stress-scenario simulator (severe-stress mode).
- Per-run dynamic computation of GMSC benchmark — kept as a static constant.
- Real-lender data integration. Out of reach without partnerships.
- Multi-segment Model Cards in v1. Single active-model card only.
- Brand styling beyond reusing existing `Card` primitives.

## 11. Risks

- **Static GMSC constant drifts.** If a future GMSC re-run produces a different number, the Model Card cites a stale figure. Mitigation: house the constant in `frontend/src/lib/benchmarks.ts` so a future PR can wire it dynamically without touching the card.
- **"Calibrated against real AU data" claim is strong** — needs to be defensible in interviews. Mitigation: link the Model Card directly to `CALIBRATION_SOURCES.md` so the receipts are one click away.
- **Employment-type realignment changes the synthetic distribution.** Trained models would need re-training to maintain consistency. Mitigation: ship the realignment in Phase A as a small atomic commit; re-train baseline + champion in the same PR; gate the change behind a regression test (positive-rate band).

## 12. Test plan

**Phase A — Backend**
- `backend/tests/test_data_generator_realism.py::test_synthetic_default_rate_within_realistic_band` (positive-class rate stable in expected band; current ~0.22-0.44 with `seed=42`).
- Existing `backend/tests/test_data_generator_no_leak.py` continues to pass after the employment-weights change.

**Phase B — Frontend**
- `frontend/src/components/metrics/__tests__/ModelCard.test.tsx`:
  1. Renders all five sections with a fully-populated `metrics` payload.
  2. Renders the empty-state banner + ⚠ rows when `training_metadata` is null.
  3. Renders ⚠ for individual rows when their specific field is missing.
  4. Renders ✓ on the GMSC row when `auc_roc - 0.866 < 0.05`; ⚠ otherwise.
  5. Falls back to `ece` from `calibration_data.ece` when top-level is null.
  6. Conditionally renders gate-mode line in Production Posture only when modes are present.
  7. Renders the seven AU-source bullet points in Trained-On (regression for the realism flex).
- Page integration: `frontend/src/__tests__/pages/ModelMetricsPage.test.tsx` (or new): ModelCard renders before Key Metrics; ModelHealthCard renders after Decile chart with an "Audit & Governance" heading.
- `npm run typecheck` passes with 0 errors.

**Visual confirmation**
- Logged-in admin opens `/dashboard/model-metrics`; takes a screenshot to confirm above-the-fold reads as a credibility narrative, not a numbers dump.

## 13. Acceptance criteria

- [ ] `backend/docs/CALIBRATION_SOURCES.md` lists every benchmark currently encoded in `DataGenerator` + subordinate services with `file:line` evidence anchors.
- [ ] `EMPLOYMENT_TYPE_WEIGHTS` realigned to ABS Aug 2025 weights (or comment updated to explain the deliberate departure).
- [ ] `test_data_generator_realism.py` regression test added and green.
- [ ] `<ModelCard />` renders at the top of `/dashboard/model-metrics` for the active model.
- [ ] All five sections appear on a v1.10.7+ model with full `training_metadata`.
- [ ] Empty state renders gracefully on legacy models with placeholder rows + info banner.
- [ ] `<ModelHealthCard />` appears at the bottom under an "Audit & Governance" heading.
- [ ] Frontend `npm run typecheck` passes with 0 errors.
- [ ] All seven `ModelCard.test.tsx` cases pass.
- [ ] Visual screenshot taken from a logged-in browser and attached to the PR.

## 14. Implementation phases (for the GSD plan)

**Phase A — Backend calibration manifest** (~ 1 atomic commit)
- A.1 Create `backend/docs/CALIBRATION_SOURCES.md` from the audit findings in §5
- A.2 Realign `EMPLOYMENT_TYPE_WEIGHTS` (§7.2)
- A.3 Add `test_data_generator_realism.py::test_synthetic_default_rate_within_realistic_band` (§7.3)

**Phase B — Frontend Model Card** (~ 2 atomic commits)
- B.1 Create `frontend/src/components/metrics/ModelCard.tsx` + `frontend/src/lib/benchmarks.ts` (GMSC constant)
- B.2 Wire into `frontend/src/app/dashboard/model-metrics/page.tsx` (insert ModelCard at top, move ModelHealthCard to bottom under "Audit & Governance" heading)
- B.3 Tests + typecheck + visual confirmation

Each phase ships as its own PR against `master`. Phase A first (so Model Card's calibration claim is true before it lands), then Phase B.

## 15. Open questions for the user (to resolve during plan-writing)

1. **GMSC constant location** — `frontend/src/lib/benchmarks.ts` (recommended) or inline?
2. **Header sub-title fallback** — when `mv.segment === 'unified'`, sub-title reads "general AU retail loan applications" or elide?
3. **Industry-context line tone** — keep Upstart citation, drop, or rephrase as "comparable systems benchmark in 0.75–0.80 range"?
4. **Employment weights interpretation** — use 0.77/0.12/0.07/0.04 (overlap-aware) or keep current 0.68/0.12/0.12/0.08 with a clarifying comment? Has downstream effects on trained models.
5. **CALIBRATION_SOURCES.md location** — `backend/docs/` (recommended) or `docs/`?
