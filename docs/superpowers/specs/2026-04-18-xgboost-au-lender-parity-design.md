# Arm A — XGBoost & Decisioning Production Parity with AU Lenders

**Status:** Draft (awaiting user review)
**Date:** 2026-04-18
**Author:** Claude (brainstorming session with user delegation)
**Scope:** Single spec; Arms B (stress-test uplift) and C (ml_engine code-review sweep) are follow-up specs.
**Supersedes:** none
**Target version:** v1.10.0

## 1. Goal

Bring the ML decisioning stack to a level that would pass a senior AU lending risk team's pre-audit review at a Big-4 (NAB, CBA) or neobank-challenger (Judo, Athena, Plenti) level. The project already has strong AU realism (HEM table, income shading by employment type, APRA 3pp + 5.75% floor, R01–R70 reason codes, BNPL/CCR/CDR features). This spec closes the gaps a risk, compliance, or model-governance reviewer would flag on inspection.

All decisions are grounded in:
- `.tmp/research/*.md` — observed practice at CBA, NAB, Judo, Plenti, MoneyMe, Wisr, Up, Alex, Canstar.
- APRA CPS 220 (risk management), APS 113 / APS 220 (credit risk), CPS 230 (operational risk).
- ASIC RG 209 (responsible lending conduct), RG 98 (reasons for decisions), DDO (TMD compliance).
- NCCP Act s.128 (written "not unsuitable" assessment record).

## 2. Non-negotiable principles

1. **Credit policy is deterministic; the model is probabilistic.** Real AU lenders run hard rules (visa type, min credit score, LVR caps, bankruptcy, ATO default) *around* the model, not inside it. A probabilistic approval of an 18-year-old visa-600 holder is a compliance breach regardless of PD.
2. **Monotonicity is required to pass MRM review.** Every feature fed to the model must have a known, defensible sign — or be explicitly marked unconstrained with a rationale. A model that can learn "higher credit score → higher default" is not audit-ready even if AUC is good.
3. **Segment decomposition reflects product reality.** Owner-occupier home loans, investor home loans, and unsecured personal loans are three separate products at every AU lender. Training one model across all masks segment-specific risk drivers.
4. **Every decision is auditable for 7 years (NCCP s.128).** Decision record must include `(pd, tier, policy_hits, reason_codes_top_4, referral_flag, shap_top_4, model_version_id, feature_snapshot)`.
5. **Hardship flags refer, never auto-decline.** Per AFCA/ASIC 2023 guidance, auto-declining applicants with hardship history can breach good-faith obligations. These referrals are handled at the audit-record level, not the customer-visible review queue (which remains bias-only per user's established preference).
6. **User's existing constraints carry over.**
   - Bias review queue stays **bias-only** (filter `bias_reports__flagged=True` unchanged).
   - Denial emails remain apology-free and compliant (no NCCP-Act name, no repetition).
   - All changes safe, reversible, tested.

## 3. Scope: 8 Deliverables

Each deliverable is independently testable and mergeable. Recommended merge order: D8 → D1 → D2 → D3 → D5 → D4 → D7 → D6.

### D1. XGBoost monotone constraints

**New file:** `backend/apps/ml_engine/services/monotone_constraints.py`

Single source of truth for feature-direction signs, consumed by `trainer.py`. Signs encoded as dict `{feature_name: +1 | -1 | 0}`:

Direction logic (abbreviated; full table in the module):
- **−1 (more → less risk):** `annual_income`, `uncommitted_monthly_income`, `net_monthly_surplus`, `savings_balance`, `credit_score`, `avg_monthly_savings_rate`, `income_verification_score`, `credit_history_months`, `employment_length`, `months_since_last_default`, `deposit_ratio`, `debt_service_coverage`, `savings_to_loan_ratio`
- **+1 (more → more risk):** `debt_to_income`, `lvr`, `loan_to_income`, `num_defaults_5yr`, `num_late_payments_24m`, `worst_arrears_months`, `credit_utilization_pct`, `num_hardship_flags`, `num_dishonours_12m`, `days_in_overdraft_12m`, `stress_index`, `stressed_dsr`, `stressed_repayment`, `hem_gap`, `bnpl_late_payments_12m`, `num_credit_enquiries_6m`, `gambling_spend_ratio`, `overdraft_frequency_90d`, `expense_to_income`, `credit_card_burden`
- **0 (unconstrained — interaction-dominant or ambiguous):** `loan_term_months`, `property_growth_12m`, `rba_cash_rate`, `consumer_confidence`, `employment_stability`, all one-hot dummies, interaction features (`lvr_x_dti`, `income_credit_interaction`, etc.), derived-log features.

Total: ~30 signed + ~20 unconstrained. Module exports:
- `MONOTONE_CONSTRAINTS: dict[str, int]`
- `build_xgboost_monotone_spec(feature_cols: list[str]) -> str` returning the `"(1,0,-1,...)"` string XGBoost consumes.
- `RATIONALE: dict[str, str]` — one-line rationale per signed feature, surfaced in MRM dossier.

**Trainer change:** `ModelTrainer.train(algorithm='xgb')` adds `monotone_constraints=build_xgboost_monotone_spec(feature_cols)` to `XGBClassifier` kwargs. Preserved in the Optuna objective.

**Test (`test_monotone_constraints.py`):** feature coverage (every numeric col in `NUMERIC_COLS` is either signed or unconstrained — none missing); RATIONALE present for every signed entry.

**Invariance test (`test_monotonicity_invariants.py`):** trains on a small synthetic dataset, then for 20 fixed applicants verifies:
- Sweeping `annual_income` from $40k → $200k: PD must be non-increasing.
- Sweeping `num_defaults_5yr` from 0 → 3: PD must be non-decreasing.
- Sweeping `credit_score` from 500 → 800: PD must be non-increasing.
- Sweeping `lvr` from 0.5 → 0.95: PD must be non-decreasing.

If the test fails, the constraint table is wrong or the XGBoost build dropped constraints silently.

### D2. Segmented model training

**New migration:** `0009_add_segment_to_modelversion.py` — adds `ModelVersion.segment = CharField(choices=[(UNIFIED, 'unified'), (HOME_OWNER_OCCUPIER, 'home_owner_occupier'), (HOME_INVESTOR, 'home_investor'), (PERSONAL, 'personal')], default=UNIFIED)`.

**Trainer change:** `ModelTrainer.train(..., segment='unified')` filters training data by segment before fitting:
- `home_owner_occupier`: `purpose='home'`
- `home_investor`: `purpose='investment'`
- `personal`: `purpose IN ('personal', 'debt_consolidation', 'car')`
- `unified`: no filter (back-compat)

Fallback: if segment has <500 samples, log warning and train unified instead, setting `ModelVersion.segment=UNIFIED` in the saved artefact.

**Management command change:** `train_model --segment home_owner_occupier` (default `unified` for back-compat).

**Predictor change:** `ModelPredictor.predict(features)`:
1. Determine segment from `features['purpose']`.
2. Look up active `ModelVersion` for that segment; fall back to unified if none active.
3. Score through selected model.
4. Include `model_version.segment` in decision metadata.

**Test (`test_segmented_training.py`):** train 3 segment models on a synthetic dataset; verify predictor routes `purpose='investment'` to investor model, `purpose='personal'` to personal model. Verify fallback to unified when a segment has no active model.

### D3. Hard credit policy overlay

**New file:** `backend/apps/ml_engine/services/credit_policy.py`

Deterministic policy engine running before the model. Mirrors how CBA/NAB apply policy independently of scoring.

```python
@dataclass(frozen=True)
class PolicyResult:
    decision: Literal["pass", "hard_fail", "refer"]
    hard_fails: tuple[str, ...]   # codes like ("P03", "P05")
    refer_flags: tuple[str, ...]  # codes like ("P08", "P10")
    rationale: dict[str, str]     # code -> human-readable reason

def evaluate(application: dict) -> PolicyResult: ...
```

Rules (code + condition + action):

| Code | Condition | Action | Source |
|------|-----------|--------|--------|
| P01  | Visa sub-class ∈ {417, 600} OR visa expiry < loan_term_months+1 | HARD_FAIL | CBA eligibility page |
| P02  | Age at application <18 OR age at maturity >75 | HARD_FAIL | Universal AU standard |
| P03  | `has_bankruptcy=1` AND months_since_discharge <60 | HARD_FAIL | Big-4 standard |
| P04  | `ato_default_flag=1` | HARD_FAIL | Industry standard |
| P05  | `credit_score < 500` (personal) or `< 600` (home) | HARD_FAIL | Per-segment threshold |
| P06  | `purpose ∈ {home, investment}` AND LVR > 0.95 | HARD_FAIL | APRA LVR cap |
| P07  | `debt_to_income > 9.0` | HARD_FAIL | NAB public threshold |
| P08  | `purpose ∈ {home, investment}` AND LTI > 7.0 | REFER | NAB public threshold |
| P09  | `postcode_default_rate > 0.15` | REFER | Existing feature threshold |
| P10  | `employment_type=self_employed` AND `employment_length < 24` | REFER | CBA eligibility requirement |
| P11  | `num_hardship_flags > 0` | REFER (not FAIL) | AFCA/ASIC 2023 guidance |
| P12  | TMD-fit check fails (simple placeholder: `loan_amount > TMD_MAX` for product) | REFER | DDO compliance |

**Integration:** `ModelPredictor.predict()` now reads:
```
policy = credit_policy.evaluate(features)
if policy.decision == "hard_fail":
    return Decision(action="declined", policy_codes=policy.hard_fails, model_skipped=True, ...)
else:
    pd_score = model.predict_proba(...)
    return Decision(
        action=...,
        pd_score=pd_score,
        policy_codes=policy.refer_flags,  # informational for refer
        referral_flag=(policy.decision == "refer"),
        ...
    )
```

**Hard_fail short-circuits model scoring entirely** — matches real AU practice (policy reject = no scorecard waste, no spurious reason codes).

**Test (`test_credit_policy.py`):** one fixture per code × (pass / fail) = 24 cases. Plus one integration fixture that triggers multiple codes simultaneously (e.g. visa-600 + DTI 10.5) — must return all hard_fail codes.

### D4. Risk-based pricing tiers

**New file:** `backend/apps/ml_engine/services/pricing_engine.py`

Maps `(pd_score, segment)` → `PricingTier`:
- **Personal loan bands** (NAB-published 7–21% range):
  - Tier A (PD ≤ 0.03): 7.0–9.5%
  - Tier B (PD ≤ 0.07): 9.5–14.0%
  - Tier C (PD ≤ 0.15): 14.0–19.0%
  - Tier D (PD ≤ 0.25): 19.0–24.0%
  - Decline (PD > 0.25)
- **Home loan bands** (tighter risk appetite; current AU home loan market 6.0–9.0%):
  - Tier A (PD ≤ 0.01): 6.0–6.5%
  - Tier B (PD ≤ 0.03): 6.5–7.2%
  - Tier C (PD ≤ 0.06): 7.2–8.0%
  - Tier D (PD ≤ 0.10): 8.0–9.0%
  - Decline (PD > 0.10)

Output attached to decision payload. Used by email layer (surfaces indicative rate band) and admin UI.

**Test (`test_pricing_engine.py`):** boundary cases (PD at exact tier boundary; segment match; invalid segment raises). 20+ parametrised cases.

### D5. KS, PSI, Brier decomposition + champion-challenger promotion gates

**Modify** `backend/apps/ml_engine/services/metrics.py`:
- `ks_statistic(y_true, y_proba) -> float` — max |F₁(s) − F₀(s)|.
- `psi(expected_dist, actual_dist, bins=10) -> float`.
- `psi_by_feature(X_ref, X_cur, feature_cols) -> dict[str, float]`.
- `brier_decomposition(y_true, y_proba, bins=10) -> dict` with keys `reliability`, `resolution`, `uncertainty`, `brier`.

**Modify** `trainer.py` — training metrics payload gains:
- `ks` (float)
- `psi_by_feature` (dict, reference = training distribution)
- `brier_decomp` (dict)

**Modify** `backend/apps/ml_engine/services/model_selector.py` — add `promote_if_eligible(candidate_version)`:
- Compare candidate vs current active champion.
- Promotion requires **all**:
  - `candidate.ks ≥ champion.ks - 0.015`
  - `max(candidate.psi_by_feature.values()) ≤ 0.25`
  - `candidate.expected_calibration_error ≤ 0.03`
  - `candidate.auc_test ≥ champion.auc_test - 0.02`
- If any gate fails, candidate stays `is_active=False` and failure reasons logged.

**Test (`test_metrics_production_grade.py`):** KS, PSI, Brier decomposition numerically match reference implementations (use tiny hand-verified fixtures). Promotion gate rejects a deliberately weak challenger, accepts a deliberately strong one.

### D6. Credit-referral audit record (no customer-facing UI in this spec)

**Rationale:** User has an established preference that the human-review queue stays bias-only. Adding a second customer-facing review queue violates that preference and would be half-finished scaffolding without an operator workflow on the other side.

**Instead**, referrals are persisted as **audit records** on the decision and exposed via API for future ops tooling. No new UI.

**Modify** `backend/apps/loans/models.py`:
- `LoanApplication.referral_status = CharField(choices=[NONE, REFERRED, CLEARED, ESCALATED], default=NONE)`
- `LoanApplication.referral_codes = JSONField(default=list)` — list of P-codes that triggered referral.
- `LoanApplication.referral_rationale = JSONField(default=dict)` — code→text map for audit.

**Populated by** `ModelPredictor.predict()` — when `policy.decision == "refer"`, write `referral_status=REFERRED`, `referral_codes=list(policy.refer_flags)`.

**API** (new endpoint, admin-only): `GET /api/loans/referrals/` returns referred applications, filterable by code, for future ops tooling. No new React UI in Arm A.

**Test:** integration test verifies referral_codes populated when P08/P09/P10/P11/P12 trigger; bias review queue filter `bias_reports__flagged=True` remains unchanged (regression guard).

### D7. Model Risk Management dossier

**New file:** `backend/apps/ml_engine/management/commands/generate_mrm_dossier.py`

`python manage.py generate_mrm_dossier <model_version_id>` writes `models/<id>/mrm.md` containing:

1. **Header** — model id, segment, algorithm, trained at, training duration, training data size.
2. **Purpose & limitations** — per segment (e.g. "For PD estimation on AU retail personal loans up to $55k, 1–7yr term. Not validated for business lending, secured non-home lending, or applicants outside AU residency.")
3. **Data lineage** — source, synthetic vs real, class balance, reject-inference usage, temporal coverage.
4. **Monotonicity constraint table** — from `monotone_constraints.RATIONALE`.
5. **Performance** — AUC/KS/Brier/ECE on train/val/test + temporal CV + baseline LR gap.
6. **Calibration report** — expected vs observed default rate by decile.
7. **PSI by feature** — stability on validation vs training.
8. **Fairness audit** — cross-reference to `intersectional_fairness.py` output.
9. **Policy overlay reference** — list of active P-codes and thresholds at time of training.
10. **Ongoing monitoring plan** — PSI alert threshold (0.25), ECE re-validation cadence (quarterly), retraining trigger (cumulative PSI > 0.5 or KS drop > 5pp).
11. **Change log** — diff vs previous ModelVersion on same segment.

**Auto-generated hook** — in `ModelVersion.save()` post-save signal, enqueue MRM dossier generation as a Celery task (`ml` queue). Non-blocking; failure logs warning, doesn't block save.

**Test:** `test_mrm_dossier_generation.py` — trains a small model, runs command, asserts generated md contains each of the 11 sections and no TODO/placeholder strings.

### D8. Predictor.py cleanup (finish uncommitted work)

**Current state:** `backend/apps/ml_engine/services/predictor.py` has 27 uncommitted lines defining `_recompute_lmi` inline inside `_get_stress_scenarios`, duplicated across two scenario blocks, plus the ceiling bump `effective_loan_amount: (0, 5_200_000)`.

**Changes:**
- Lift `_recompute_lmi` to module level as `_recompute_lvr_driven_policy_vars(features: dict) -> dict` (returns modified copy, does not mutate).
- Call sites in `_get_stress_scenarios` use the module-level helper.
- Keep the `effective_loan_amount` ceiling bump (correct fix for 5M loan + 150k LMI headroom).
- Unit test `test_stress_scenario_lmi_recomputation.py`: stress scenario with `property_value=$1.2M, loan_amount=$1.0M` must re-derive `lmi_premium` based on stressed-LVR (not base-LVR), and stressed-LVR must push the applicant into a higher LMI bracket.

## 4. Decision-time data flow

```
POST /api/loans/applications/{id}/predict
  │
  ▼
ModelPredictor.predict(features)
  │
  ├─── credit_policy.evaluate(features)  ← D3
  │      ├─ hard_fail? → return Decision(action="declined",
  │      │                               policy_codes=hard_fails,
  │      │                               model_skipped=True,
  │      │                               reason_codes=[])
  │      └─ pass/refer → continue
  │
  ├─── segment = derive_segment(features)             ← D2
  ├─── model = select_active_model(segment)           ← D2
  ├─── pd_score = model.predict_proba(...)            ← trained with D1 constraints
  │
  ├─── tier = pricing_engine.get_tier(pd_score, segment)    ← D4
  ├─── shap_top4 = compute_shap(model, features)
  ├─── reason_codes = generate_adverse_action_reasons(...)  ← existing R01-R70
  │
  ├─── referral_flag = policy.decision == "refer"
  └─── return Decision(
         action="approved@tier" | "declined" | "referred",
         pd_score,
         tier,
         policy_codes=policy.refer_flags,
         referral_flag,
         reason_codes,
         shap_top4,
         model_version_id=model.version.id,
         feature_snapshot=sanitised_features,
       )
```

## 5. Testing strategy

- **Unit** — 7 new test files (one per deliverable except D6 which modifies existing tests).
- **Invariance** — `test_monotonicity_invariants.py` enforces model behaviour, not just training metrics.
- **Integration** — `test_decision_pipeline_end_to_end.py` with ≥10 synthetic applicants covering:
  - Clean approve (low PD, no refer).
  - Hard fail (visa 417 → no model score generated; reason = P01 only).
  - Multiple hard fails (visa + DTI → both codes surface).
  - Refer (self-employed 18mo + LTI 7.5 → referred, model scored, PD surfaced).
  - Hardship-flag refer (P11 — must not auto-decline).
  - High PD decline (tier=decline, pd > 0.25 personal).
  - Home owner-occupier routed to segmented model.
  - Home investor routed to investor model.
  - Fallback to unified when segment model missing.
- **Regression gate** — golden file `models/golden_metrics.json` pins current AUC/KS/Brier. CI fails if retraining drops AUC >2pp or KS >1.5pp.
- **Load** — Locust batch of 100 concurrent requests through the full pipeline; must sustain <500ms p95.

## 6. File map

**NEW (9 files):**
- `backend/apps/ml_engine/services/monotone_constraints.py`
- `backend/apps/ml_engine/services/credit_policy.py`
- `backend/apps/ml_engine/services/pricing_engine.py`
- `backend/apps/ml_engine/management/commands/generate_mrm_dossier.py`
- `backend/apps/ml_engine/migrations/0009_add_segment_to_modelversion.py`
- `backend/apps/loans/migrations/<next>_add_referral_fields.py`
- `backend/apps/ml_engine/tests/test_monotone_constraints.py`
- `backend/apps/ml_engine/tests/test_monotonicity_invariants.py`
- `backend/apps/ml_engine/tests/test_credit_policy.py`
- `backend/apps/ml_engine/tests/test_pricing_engine.py`
- `backend/apps/ml_engine/tests/test_segmented_training.py`
- `backend/apps/ml_engine/tests/test_metrics_production_grade.py`
- `backend/apps/ml_engine/tests/test_mrm_dossier_generation.py`
- `backend/apps/ml_engine/tests/test_decision_pipeline_end_to_end.py`
- `backend/apps/ml_engine/tests/test_stress_scenario_lmi_recomputation.py`

**MODIFY:**
- `backend/apps/ml_engine/services/trainer.py` — monotone constraints, segment, KS/PSI/Brier
- `backend/apps/ml_engine/services/predictor.py` — policy overlay, segment routing, `_recompute_lvr_driven_policy_vars` extract
- `backend/apps/ml_engine/services/model_selector.py` — promotion gates
- `backend/apps/ml_engine/services/calibration_validator.py` — decile report for MRM
- `backend/apps/ml_engine/services/metrics.py` — KS, PSI, Brier decomposition
- `backend/apps/ml_engine/management/commands/train_model.py` — `--segment` flag
- `backend/apps/ml_engine/models.py` — `ModelVersion.segment` field
- `backend/apps/ml_engine/views.py` — expose tier, policy_codes, referral_flag in decision payload
- `backend/apps/loans/models.py` — referral_status / codes / rationale fields
- `backend/apps/loans/views.py` — admin-only referrals endpoint

## 7. Explicit out-of-scope (will become separate specs)

- **Arm B** — Portfolio stress testing uplift. `stress_testing.py` currently hardcodes rate 6.5% and expense ratio 35%; needs configurable macro scenarios (RBA cash-rate path, unemployment, HPI), APRA CPS 220 severely-adverse, PD-stability under shock (PSI + KS before/after).
- **Arm C** — ml_engine/services/ code-review sweep. 6 files >500 LOC (trainer 1259, data_generator 1555, predictor 1078, calibration_validator 536). Break up responsibilities, deduplicate, add integration coverage.
- Customer-facing referral queue UI — blocked on having a defined ops workflow; intentionally not shipped in Arm A.
- Real Equifax/Illion bureau integration — requires SaaS contract.
- TMD document ingestion — Arm A uses a simple placeholder check (loan_amount limit). True TMD compliance needs product-catalogue work.

## 8. Success criteria

- [ ] `monotone_constraints.py` has signs for ≥30 features, unconstrained rationale for 15+, RATIONALE dict present.
- [ ] XGBoost training uses constraints; invariance tests pass on 20+ synthetic applicants.
- [ ] Three segmented models trainable; predictor routes correctly; fallback to unified works.
- [ ] Credit policy overlay blocks visa/age/bankruptcy/ATO/score/LVR/DTI hard-fails deterministically.
- [ ] Refer flags populate `LoanApplication.referral_*` fields; bias review queue filter unchanged.
- [ ] KS/PSI/Brier decomposition in training metrics; promotion gate enforced; challenger rejection logged.
- [ ] Pricing tier returned on every approval decision; NAB-consistent personal band; tighter home band.
- [ ] MRM dossier auto-generates on ModelVersion save; covers all 11 sections.
- [ ] Predictor.py cleanup merged; `_recompute_lvr_driven_policy_vars` module-level; unit-tested.
- [ ] Golden metric file locks AUC/KS/Brier; CI fails on >2pp AUC drop.
- [ ] End-to-end pipeline sustains <500ms p95 at 100 RPS.
- [ ] All existing tests stay green (no regressions in bias pipeline, email flow, existing reason codes).

## 9. Rollout

1. Branch from `feat/realism-hem-lmi-features` (currently has D8 work in progress). Rebase onto master once v1.9.9 is merged.
2. Implement D8 first (finishes unfinished work, clears predictor.py).
3. D1 + D2 + D5 in order — these are the model-training changes that need a retrain to demonstrate.
4. Retrain + measure + commit golden metric file.
5. D3 + D4 + D6 — decisioning pipeline changes.
6. D7 — MRM dossier (integrates all prior output).
7. Integration tests + load tests + bump APP_VERSION to 1.10.0.
8. One PR per deliverable (8 PRs), stacked in merge order.

## 10. Risks & mitigations

- **AUC drop from monotone constraints.** Typical cost 1–2pp. Mitigate by setting golden-file threshold at −2pp and retuning Optuna within constraint space.
- **Segment data sparsity.** <500 samples in a segment triggers fallback; acceptable short-term. Long-term: retrain synthesis to generate per-segment volumes.
- **Policy overlay false positives.** A clean applicant hard-failed on a misconfigured policy rule is a customer-experience incident. Mitigate with 24 × (pass/fail) fixture tests, shadow-mode rollout (log decisions but still let model run for 2 weeks), then enforce.
- **MRM dossier generation blocks ModelVersion save.** Mitigate by enqueuing as Celery task; save completes even if dossier fails.
- **Existing tests regressing.** Mitigate by running full test suite on every deliverable branch before merge; retain all existing pipeline tests.
