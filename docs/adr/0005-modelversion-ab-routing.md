# ADR-0005: ModelVersion A/B routing

**Status:** Accepted
**Date:** 2026-04-15
**Deciders:** Neville Zeng

## Context

When a new model version is ready, we need to route a controlled percentage of traffic to it to measure real-world performance before committing. Options span feature-flag services (LaunchDarkly), shadow deploys (run both, log, serve one), and inline weighted selection.

## Decision

We will use a `traffic_percentage` integer column on `ModelVersion` (0–100), with `is_active=True` on one or more versions. `apps.ml_engine.services.model_selector.select_model_version` picks the active version weighted-randomly per call. A single active version is the fast path; multiple active versions trigger weighted sampling.

## Alternatives Considered

- **LaunchDarkly / Unleash** — Rejected for a portfolio project: operational overhead, monthly cost, external dependency. The principle (percentage rollout) is embedded directly.
- **Shadow deploy** — Considered, not mutually exclusive. Can be layered later by running the challenger in a non-blocking "log only" mode.
- **Per-user bucketing (hash(user_id) % 100 < pct)** — Rejected for now: simpler stateless random works for current scale, where individual users rarely make repeated decisions in the same session. Revisit if we see user-level variance in outcomes.

## Consequences

**Positive:**
- Dead simple — one column, one service, one query
- Rollout can be adjusted without deploying code
- Single-active-version fast path is branch-predictable

**Negative:**
- Per-request random means the *same user* can hit different models across requests — acceptable at current scale, but would confuse A/B analysis if user-level outcomes matter
- No sticky bucketing — requires a denormalised `model_version_used` on decisions for retrospective analysis (already present on `LoanDecision`)
- No chi-square / significance testing built in — future work

## References

- `backend/apps/ml_engine/models.py` — `ModelVersion.traffic_percentage`
- `backend/apps/ml_engine/services/model_selector.py`
- `backend/tests/test_champion_challenger.py`
