# Agent Pipeline Completeness: Second Bias Agent, Offers in Denials, Overfit Gate, Ad-hoc Scoring

Date: 2026-10-02
Status: approved design, ready for implementation planning

## Purpose

Four gaps remain between how the three-level system is meant to work and how it
works today:

1. A decision email in the moderate bias band (score 31-59) has no second agent.
   On master it ships as written. Open PR #275 replaces it with the fixed
   template, so the customer gets the generic email even when a corrected
   LLM email would have been fine.
2. The next-best offer appears only in LLM-written denial emails. Template
   denials, including the #275 replacement, drop it.
3. The overfitting check compares train AUC with test AUC and only logs a
   warning. Nothing stops an overfit model from being promoted, and the check
   uses the test set, which should stay untouched until the final measurement.
4. Staff cannot score one applicant against the active model without creating
   a loan application. The standalone predict endpoint is disabled by default
   and needs an existing application.

## Delivery

Four atomic PRs in two stacks, following the open review stacks so nothing
conflicts:

| PR | Branch | Base |
|----|--------|------|
| A  | `feat/bias-agent2-regenerate` | `fix/bias-moderate-band-regenerate` (#275) |
| B  | `feat/denial-template-offer` | PR A |
| C  | `feat/validation-overfit-gate` | `fix/metrics-threshold-provenance` (#274) |
| D  | `feat/adhoc-applicant-scoring` | PR C |

Each stack is worked in its own git worktree.

## A. Second agent for the moderate bias band

Files: `backend/apps/agents/services/email_pipeline.py`,
`backend/apps/email_engine/services/email_generator.py`,
`backend/apps/email_engine/services/decision_email.py`,
`backend/config/settings/base.py`.

### Flow

The severe band (score >= `BIAS_THRESHOLD_REVIEW`, default 60) is unchanged: it
escalates to human review. For a flagged email below that threshold:

1. **Agent 2 regeneration.** Runs when all of these hold:
   `BIAS_AGENT2_ENABLED` is true, the flagged email was LLM-written (not
   `template_fallback`), and generation succeeds. The generator writes a new
   email with the bias findings (categories and analysis) supplied as
   feedback, through a new keyword argument `bias_feedback` on
   `EmailGenerator.generate`. The feedback goes into the prompt in the same
   form as guardrail retry feedback. The same `profile_context` is passed, so
   the denial offer is kept. The new email is persisted as its own
   `GeneratedEmail` and passes through the normal guardrail retry loop.
2. **Stricter re-check.** The regenerated email must pass two checks:
   - `BiasDetector.analyze` returns `flagged = False`.
   - `AIEmailReviewer.review` (the senior reviewer, which is already written
     but has never run on decision emails) returns `approved = True` with
     `confidence >= 0.70`.
   A `BiasReport` is saved for the detector result. The reviewer verdict is
   recorded in the step's `result_summary`. If both checks pass, the
   regenerated email is the one delivered.
3. **Template fallback.** Agent 2 hands over to the existing #275 path
   (`replace_flagged_email`: template, then re-check, then send if clean or
   escalate if flagged) in each of these cases:
   - Agent 2 is skipped (disabled, or the original was already the template).
   - Agent 2 raises (provider error, rate limit, budget cap).
   - The regenerated email fails guardrails.
   - The detector flags the regenerated email.
   - The reviewer rejects it or approves with low confidence.

### Recording

- The new step `bias_agent2_regeneration` records `regenerated`, `bias_score`,
  `flagged`, `reviewer_approved`, `reviewer_confidence` and, when Agent 2 hands
  over, `reason`.
- Waterfall code `EMAIL_REGENERATED_AGENT2` is written when the Agent 2 email
  is the one sent.
- A hand-over writes no waterfall entry of its own. The template path that
  follows writes its existing entries.

### Cost

LLM spend happens only in the moderate band. The most a single email can cost
is one regeneration (up to `MAX_RETRIES` guardrail attempts), one bias-detector
LLM call and one reviewer call. The existing daily budget gate applies, and
when the gate refuses, the template path takes over.

### Settings

`BIAS_AGENT2_ENABLED` (env, default `true`). When it is false, behaviour is
exactly #275.

## B. Offer inside every denial email

Files: `backend/apps/email_engine/services/template_fallback.py`,
`backend/apps/email_engine/services/email_generator.py`,
`backend/apps/email_engine/services/decision_email.py`,
`backend/apps/agents/services/email_pipeline.py`.

- `generate_denial_template` takes an optional `nbo_offer`. When an offer is
  given, it renders the same block the LLM prompt uses. `_render_nbo_block`
  moves to a module-level helper that both paths call, so the wording matches
  exactly.
- `EmailGenerator.generate_template` and `generate_template_decision_email`
  accept `profile_context`. The template path adds `nbo_offers` and the offer
  amounts to the guardrail context, as the LLM path already does, so the offer
  figures do not trip the hallucinated-number check.
- The pipeline passes `profile_context` to the template replacement, and
  `generate_decision_email` passes it to its rate-limit template fallback.
- The block contains no apology or emotional language (locked project rule).
  An approval email never gets an offer.
- The separate consent-gated marketing email is unchanged.

## C. Validation-set overfitting gate

Files: `backend/apps/ml_engine/services/training/trainer.py`,
`backend/apps/ml_engine/services/activation.py`,
`backend/config/settings/base.py`, the Model Metrics frontend tab that shows
AUC.

- The trainer computes `val_auc` on the validation split with the final
  (calibrated) model, then `overfitting_gap_val = train_auc - val_auc`. Both
  are stored in the version's metrics. `overfitting_gap` (train vs test) is
  still reported, as the final honest figure.
- `_evaluate_gates` gets an `overfitting` gate. It fails when
  `overfitting_gap_val > ML_OVERFIT_MAX_GAP` (env, default `0.05`). It follows
  `ML_PROMOTION_GATE_MODE` (warn/block/off), like the other gates. A version
  trained before this change has no `overfitting_gap_val`. Its gate reports
  "not assessable" and never blocks.
- The Model Metrics page shows train, validation and test AUC side by side,
  with the gap and the gate result.
- Known limitation, stated in the UI caption and the model card: the
  validation split also drives XGBoost early stopping, calibration and
  threshold choice, so the validation gap slightly understates true
  overfitting. The test gap stays as the independent check.

## D. Ad-hoc applicant scoring

Files: `backend/apps/ml_engine/views.py`, `backend/apps/ml_engine/urls.py`, a
new serializer, and a new "Try it" tab on the Model Metrics page.

- `POST /api/v1/ml/models/active/score/`. Permission `IsAdminOrOfficer`, and a
  throttle of its own.
- The request body holds the applicant and loan fields the model reads,
  validated by the existing loan application serializer rules (bounds and
  choices).
- The view builds an unsaved `LoanApplication` in memory and calls
  `ModelPredictor.predict`. It returns `probability`, `decision` at the active
  threshold, the top SHAP reasons and `model_version`.
- Nothing is persisted: no application row and no `PredictionLog`. One
  `AuditLog` entry records the action with the submitted field names, never
  the values.
- Before the view is written, the predictor is checked for database writes or
  relation access that would fail on an unsaved instance. Any found are kept
  out of the ad-hoc path through a narrow parameter, not a second scoring
  implementation.
- Frontend: a "Try it" tab with a form prefilled from a sample applicant. The
  result is shown with the existing `ShapWaterfall` component and a
  probability/threshold readout.

## Testing

TDD for each unit. Backend tests run with pytest in the backend container,
ruff runs on the host and frontend tests run with vitest.

- A: one routing test per branch:
  - Agent 2 passes both checks and is sent.
  - The detector flags the regenerated email: template path.
  - The reviewer rejects or has low confidence: template path.
  - Agent 2 raises: template path.
  - The flagged email was already the template: Agent 2 skipped.
  - Disabled by setting: Agent 2 skipped.
  - The template path is flagged: human review.
  Also: the bias feedback reaches the prompt, and the offer survives
  regeneration.
- B: a template denial with and without an offer, the guardrails accept the
  offer figures, an approval never gets an offer, and the LLM and template
  blocks render the same text.
- C: the gap is computed on the validation split, and the gate covers fail,
  pass, missing field and each mode.
- D: permissions, validation errors, no rows written, the audit entry has no
  values, and the response shape. Frontend: the form submits and the result
  renders.

## Out of scope

- Marketing emails with a bias score of 70 or more stay blocked without human
  review.
- A stricter re-scoring threshold for the template re-check (#275 keeps the
  same detector).
- Choosing the offer from the actual denial reasons.
