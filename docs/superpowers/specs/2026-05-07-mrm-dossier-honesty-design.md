# MRM Dossier Honesty — post-Codex content fix

**Date:** 2026-05-07
**Status:** Approved design, pending implementation plan
**Scope:** Three findings from the 2026-05-06 Codex adversarial review of `backend/ml_models/7556578d-…/mrm.md`. All fixes land in the dossier generator; no runtime behaviour changes.

## Context

A Codex adversarial review of an orphan MRM dossier surfaced three correctness defects in the dossier *generator* (not the dossier file directly — the file is just the symptom). The dossier was claiming controls the runtime does not actually enforce, branding a model with failed fairness gates as APRA-aligned, and pointing operators at a 404 drift URL.

The runtime issues the review also touches on (fairness failure not blocking activation, policy overlay defaulting to `shadow`, champion-challenger gates not invoked on activation) are deliberately **out of scope** for this spec — they are larger architectural changes with real blast radius. The dossier becomes the truth-teller in the meantime, which is consistent with the existing module docstring's stance: "audit-visible evidence of gaps, rather than silent omission."

## Findings at a glance

| # | Codex severity | Surface | Fix shape |
|---|---|---|---|
| 1 | high | `mrm.md:21` ↔ `credit_policy.py:418-425` | `_purpose_section` reads `settings.CREDIT_POLICY_OVERLAY_MODE` and emits one of three explicit out-of-scope wordings (`off`/`shadow`/`enforce`) instead of an unconditional "must be referred". |
| 2 | high | `mrm.md:2-14` ↔ `tasks.py:126-133` | Drop "alignment" from the document subtitle; introduce a new `Compliance status:` line in §1 Header (COMPLIANT / NEEDS REVIEW / NON-COMPLIANT) computed from gate evidence. Failed fairness can no longer be hidden behind an active+aligned banner. |
| 3 | medium | `mrm.md:128, 175` ↔ `tasks.py:82-88`, `urls.py:8` | `_performance_section` softens "enforce these + PSI/calibration ceilings" to "exist; confirm pre-promotion review". `_monitoring_section` drift URL changes from `/api/ml-engine/drift/` to the actual `/api/v1/ml/models/active/drift/`. |

## Finding 1 — Conditional out-of-scope wording

**Problem.** `_purpose_section` (lines 94–96 of `mrm_dossier.py`) emits an unconditional "Predictions on applications outside scope **must be treated as advisory only and referred** to human underwriter review". `apply_overlay_to_decision()` only changes decisions in `enforce` mode (`credit_policy.py:418-425`); the documented default is `shadow`, which is observational. The dossier is asserting a control that is off by default.

**Chosen approach.** Read the effective overlay mode at dossier-generation time and emit an explicit, mode-specific paragraph. The §9 policy section already mentions the three-mode contract — make §2 consistent with it.

**Design.**

- Inside `_purpose_section`, deferred import: `from django.conf import settings` and read `getattr(settings, "CREDIT_POLICY_OVERLAY_MODE", "shadow")`.
- Three-way switch on the read value; unknown modes fall through to the `shadow` wording (matches `credit_policy.py:405` warning behaviour).

  | Mode | Rendered paragraph |
  |---|---|
  | `off` | "No policy overlay is active in this deployment. Out-of-scope predictions are not flagged or blocked at runtime — manual scope review is required at intake." |
  | `shadow` | "The policy overlay runs in `shadow` (observational) mode in this deployment. Out-of-scope predictions are flagged for monitoring but **not blocked**; manual underwriter review depends on operator workflow rather than automated routing (see §9)." |
  | `enforce` | "The policy overlay runs in `enforce` mode in this deployment. Out-of-scope predictions are blocked by the overlay and routed to manual underwriter review (see §9 P-codes)." |

- The `must be referred` mandate now appears **only** in the `enforce` rendering. The `shadow` wording is the new default.

**Alternative considered.** Add a `--mode-override` CLI flag to the generator. Rejected — generator should reflect actual deployment, not a hypothesis. If an operator wants to preview the `enforce` paragraph, they can run with `CREDIT_POLICY_OVERLAY_MODE=enforce` env override before invoking the management command.

**Tests.**
- Default settings (no env override) → output contains `shadow` wording, contains "**not blocked**", does not contain "must be treated".
- `@override_settings(CREDIT_POLICY_OVERLAY_MODE="enforce")` → output contains `enforce` wording with the original "blocked by the overlay" mandate.
- `@override_settings(CREDIT_POLICY_OVERLAY_MODE="off")` → output contains "No policy overlay is active".
- `@override_settings(CREDIT_POLICY_OVERLAY_MODE="bogus")` → falls through to `shadow` wording.

## Finding 2 — Compliance status banner

**Problem.** The document subtitle (built in `generate_dossier_markdown` at line 354) reads `_Generated … — APRA CPS 220 / SR 11-7 alignment_`. Combined with `**Active:** True` in §1, the dossier reads as a sign-off artifact. The fairness section can show two `passes_80_percent_rule: false` rows and the document still brands itself as "aligned". The runtime activation path leaves these models active anyway (`tasks.py:126-133`), so the dossier becomes the only line of defence — and it's currently silent.

**Chosen approach.** Demote the subtitle to neutral framing and surface a **prominent compliance status line** in §1 Header that any auditor sees on the first page. The status is derived purely from already-recorded evidence on the `ModelVersion`.

**Design.**

- New pure helper `_compliance_status(mv) -> tuple[str, list[str]]` returning a status code and a list of reasons (empty when COMPLIANT).

  Status decision (in order; first match wins):

  | Trigger | Status |
  |---|---|
  | Any `mv.fairness_metrics[*].passes_80_percent_rule == False` | **NON-COMPLIANT** |
  | Any feature in `mv.training_metadata.psi_by_feature` ≥ 0.25 | **NON-COMPLIANT** |
  | `mv.ece is not None and mv.ece > 0.05` | **NON-COMPLIANT** |
  | Any of `fairness_metrics`, `psi_by_feature`, `calibration_data.deciles` is missing/empty | **NEEDS REVIEW** |
  | Otherwise | **COMPLIANT** |

  Thresholds (`0.25` PSI, `0.05` ECE) match the existing `_psi_section` "significant drift" boundary and the standard ECE acceptance ceiling — kept as module-level constants `PSI_FAIL_THRESHOLD = 0.25`, `ECE_FAIL_THRESHOLD = 0.05` for visibility.

- Document subtitle becomes `_Generated {ts} — Format: APRA CPS 220 / SR 11-7_`. The word `alignment` is removed.

- §1 Header gains two new bullets, after `**Active:**`:
  - `- **Compliance status:** {STATUS}`
  - When status is not COMPLIANT, append a sub-list of reasons (one bullet per failure or missing-evidence reason).

- Status string is intentionally not colour-coded with emoji or HTML — markdown renders consistently across GitHub/auditor PDF/local preview, and grep-ability matters for audit tooling.

**Alternative considered.** Refuse to generate the dossier at all when `is_active=True` and any fairness gate fails. Rejected — the existing `mrm_dossier` module philosophy is "missing data degrades gracefully ... explicit 'Unavailable' line rather than silently omitting, so the auditor sees the gap." Refusing to generate would hide the gap rather than surface it.

**Tests.**
- `_compliance_status` returns `("COMPLIANT", [])` when fairness all pass + PSI all <0.25 + ECE ≤ 0.05 + calibration deciles present.
- `_compliance_status` returns `NON-COMPLIANT` with a reason mentioning the failing protected attribute when any `passes_80_percent_rule` is False.
- `_compliance_status` returns `NON-COMPLIANT` when any PSI ≥ 0.25 or `mv.ece > 0.05`, with reason naming the threshold breached.
- `_compliance_status` returns `NEEDS REVIEW` (not NON-COMPLIANT) when `fairness_metrics` is empty/missing.
- Header rendering includes `Compliance status: NON-COMPLIANT` when fairness fails, even with `is_active=True`.
- Document subtitle does not contain the word `alignment` (regression guard).
- Document subtitle still contains `APRA CPS 220 / SR 11-7` (we keep the format reference).

## Finding 3 — Promotion-gate honesty + drift URL

**Problem.** Two sub-issues bundled by Codex.

(a) `_performance_section` lines 177–179 say "Champion-challenger promotion gates (see model_selector.py) **enforce** these + PSI and calibration ceilings." But the activation path in `tasks.py:82-88` creates the new model with `is_active=True` directly without invoking those gates. The dossier overstates the runtime control.

(b) `_monitoring_section` line 298 points to `Drift dashboard: /api/ml-engine/drift/`. The actual route is `/api/v1/ml/models/active/drift/` (`urls.py:8` mounted at `api/v1/ml/` in `config/urls.py:228`). Operators following the dossier in an incident hit a 404.

**Chosen approach.** Two string changes, two regression-guard tests.

**Design.**

- `_performance_section`: replace the trailing block with:
  > "KS > 0.30 and AUC > 0.75 are the regulator-expected performance floor for AU retail-credit scorecards. Champion-challenger promotion gates **exist** in `model_selector.py` (PSI, calibration, KS); the current activation path in `tasks.py` activates new models directly, so confirm pre-promotion review for production deployments before relying on these gates."
- `_monitoring_section`: change `Drift dashboard: /api/ml-engine/drift/` → `Drift dashboard: /api/v1/ml/models/active/drift/`.

**Alternative considered.** Wire `tasks.py` activation through `model_selector` so the gates are actually enforced, making the original dossier text true. Rejected — runtime change, scope creep, separate workstream.

**Tests.**
- `_performance_section` does not contain the substring `enforce these`.
- `_performance_section` contains `gates exist` and `confirm pre-promotion review`.
- `_monitoring_section` contains exactly `/api/v1/ml/models/active/drift/`.
- `_monitoring_section` does not contain the legacy `/api/ml-engine/drift/` substring (regression guard).

## Out of scope

- **Runtime activation gating.** Making fairness failure block `tasks.py` activation, or routing activation through `model_selector` champion-challenger gates, is a separate workstream with migration concerns (currently-active models with failed fairness would need explicit deactivation paths). Track separately if pursued.
- **Overlay default change.** Switching `CREDIT_POLICY_OVERLAY_MODE` default from `shadow` to `enforce` is a deployment policy change, not a dossier change.
- **The orphan `backend/ml_models/7556578d-…/mrm.md`.** File is local-only / untracked. After this spec ships, manually choose: `rm -rf` the directory, or run `python manage.py generate_mrm_dossier 7556578d-8768-44a7-a84f-a1ad0f052cb7` to regenerate it against the live DB and inspect the new banner. Not part of the implementation plan.

## Test surface summary

All new tests live in `backend/apps/ml_engine/tests/test_mrm_dossier.py`. Existing 240 LOC of tests must still pass unchanged (regression floor). New tests use plain object fakes — same pattern as the existing `_FakeModelVersion` helper in that file — so no DB or Django boot is required.

Estimated test additions: ~12 new test functions, ~150 LOC.

## Implementation footprint

- Single touch file in `services/`: `backend/apps/ml_engine/services/mrm_dossier.py` (~50 LOC added: 1 new pure helper, 2 new module-level constants, edits to 3 sections + the document subtitle).
- Single touch file in `tests/`: `backend/apps/ml_engine/tests/test_mrm_dossier.py` (~150 LOC added).
- Zero touches anywhere else: no settings changes, no migrations, no URL changes, no runtime path edits, no frontend changes.

## Branch + PR shape

- Branch: `fix/mrm-dossier-honesty-after-codex-review`
- Single squash-merge PR. Title: `fix(ml): MRM dossier honesty — overlay-mode wording, compliance status, drift URL`.
- Commit message + PR body cite all three Codex finding tags ([high]/[high]/[medium]) and link the original review comment (PR #161 thread).
- Mirrors the project's atomic-PR pattern (cf. PRs #80–#82 for v1.9.4, #97–#102 for v1.10.1).
