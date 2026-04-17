# Coverage Phase 2 Design — 2026-04-17

## Context

v1.9.1 (2026-04-17) landed phase 1 of the external reviewer's coverage ask (#64): `testpaths` fix collected 20 previously-uncollected tests, raising backend coverage **61.35% → 63.98%**. The gate moved 60 → 63.

The reviewer's target is 75%. Phase 1 closed about 20% of the gap. Phase 2 closes most of the remainder by writing focused unit tests for the three lowest-coverage production modules.

## Goal

Raise backend test coverage to a measured, honest number by writing quality unit tests for the three lowest-coverage modules in `backend/apps/*/services/`. The target is not the 75% number itself — it is **each of the three target modules at ≥70% coverage**, with the aggregate landing wherever honest measurement places it (expected 71-74%).

## Non-goals

- Hitting 75% exactly. If quality tests land us at 72%, that is the number.
- Live Claude API calls. All LLM paths are exercised with mocked responses.
- Integration tests spanning full Celery pipelines. Existing `test_marketing_pipeline.py` already covers that; phase 2 is pure unit.
- Refactoring the three target modules. Tests are additive — the only production-code changes allowed are extracting a constant or making a private method testable (mirroring #63's `POST_OUTCOME_FEATURES` pattern).

## Target modules

| Module | LOC | Current coverage | Existing tests |
|--------|-----|------------------|----------------|
| `apps/agents/services/marketing_agent.py` | 793 | 11% | 5 pipeline-level tests in `backend/tests/test_marketing_pipeline.py` |
| `apps/ml_engine/services/counterfactual_engine.py` | 457 | 11% | 11 tests across 2 files (narrow happy-path + 1 timeout test) |
| `apps/agents/services/next_best_offer.py` | 340 | 13% | 0 dedicated test files |

Source of coverage numbers: v1.9.1 measurement from CI run 24549952863 (pre-#64 baseline, Jenkins coverage report).

## Architecture

### PR structure — three atomic PRs, one per module

Matches the v1.9.1 atomic PR pattern (#63, #64, #65). Staged coverage-gate bumps give safety against over-eager jumps.

| # | Title | Module | Estimated new tests | Gate bump |
|---|-------|--------|---------------------|-----------|
| P2-1 | `test(marketing_agent): guardrail branches + template fallback` | `marketing_agent.py` | ~30 | 63 → `measured - 0.5` (likely 68) |
| P2-2 | `test(counterfactual_engine): DiCE fallback + helpers` | `counterfactual_engine.py` | ~19 | previous → `measured - 0.5` (likely 70) |
| P2-3 | `test(next_best_offer): messaging + precalc fallback + context` | `next_best_offer.py` | ~13 | previous → `measured - 0.5` (likely 71) |

Gate bump formula: `floor(measured_coverage_percent) - 0.5`, rounded to integer. Proven pattern from #64 — tight enough to catch regressions, 0.5pt buffer against measurement noise.

### Test file layout

New files are added under each app's existing `tests/` directory. No directory restructuring.

- **NEW** `backend/apps/agents/tests/test_marketing_agent.py` — dedicated unit tests, separate from the pipeline-level `backend/tests/test_marketing_pipeline.py`.
- **NEW** `backend/apps/agents/tests/test_next_best_offer.py` — no prior file exists.
- **NEW** `backend/apps/agents/tests/conftest.py` — shared `mock_claude_response` fixture so PR-1 and PR-3 do not drift.
- **EXTENDED** `backend/apps/ml_engine/tests/test_counterfactual_engine.py` — new test classes (`TestDiCEFallback`, `TestBinarySearchConvergence`, `TestFormatStatement`) appended to existing file.

Files that change together live together. The shared `conftest.py` for `agents/tests/` eliminates duplicated Claude-mock setup between marketing and NBO tests.

## Components

### Shared: `backend/apps/agents/tests/conftest.py`

Single source of truth for the Claude-API mock shape. Both marketing_agent and next_best_offer call the Anthropic SDK the same way, so one fixture covers both.

```python
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_claude_response():
    """Return a factory that builds anthropic.Messages responses.

    Usage:
        resp = mock_claude_response("Dear customer, ...")
        with patch.object(anthropic.Anthropic, "messages") as m:
            m.create.return_value = resp
    """
    def _build(text: str, *, stop_reason: str = "end_turn"):
        return MagicMock(
            content=[MagicMock(text=text)],
            stop_reason=stop_reason,
        )
    return _build
```

### PR P2-1: marketing_agent tests (~30 tests)

Target: lift `marketing_agent.py` from 11% to ≥70%. Largest-value PR.

| Test class | Coverage target | Approx tests |
|------------|-----------------|--------------|
| `TestGuardrailCheckNoDeclineLanguage` | `_check_no_decline_language` — accept path, detect "unfortunately", detect "declined", case sensitivity | 4 |
| `TestGuardrailCheckPatronising` | `_check_patronising_language` — detect "simply", "just", "only", tone-safe baseline | 4 |
| `TestGuardrailCheckNoFalseUrgency` | `_check_no_false_urgency` — "act now", "limited time", tone-safe baseline | 3 |
| `TestGuardrailCheckNoGuaranteedApproval` | `_check_no_guaranteed_approval` — detect "guaranteed approval", "pre-approved", safe phrasing | 4 |
| `TestGuardrailCheckMarketingTone` | `_check_marketing_tone` — detect formal-letter, detect friendly-tone, neobank baseline | 3 |
| `TestGuardrailCheckMarketingFormat` | `_check_marketing_format` — detect missing sections, accept valid format | 3 |
| `TestGuardrailCheckHasCallToAction` | `_check_has_call_to_action` — detect missing CTA, accept valid CTA | 2 |
| `TestTemplateFallback` | `_marketing_template_fallback` — template rendering with NBO data, empty NBO, denial reason edge cases | 3 |
| `TestParseAndFormat` | `_parse_response` malformed input, `_format_offers` empty + multi | 3 |
| `TestRetryOnGuardrailFailure` | `_generate_with_retries` — retry on guardrail trigger, max retries exhausted → fallback | 2 |

Total: **31 tests**.

### PR P2-2: counterfactual_engine tests (~19 tests)

Target: lift `counterfactual_engine.py` from 11% to ≥70%. Existing 11 tests cover `generate()` happy path + timeout; dark areas are DiCE parse, fallback binary search, format statement.

| Test class | Coverage target | Approx tests |
|------------|-----------------|--------------|
| `TestDiCEFallback` | `_parse_dice_result` — typical DiCE output, single-feature change, multi-feature change, empty result | 4 |
| `TestBinarySearchConvergence` | `_binary_search_feature` — converge on approval in <10 iters, diverge at max-iter, numeric vs categorical feature | 5 |
| `TestFallbackSearch` | `_fallback_binary_search` — fallback triggered, feature ordering, early exit on approval | 3 |
| `TestBuildDiCEDataset` | `_build_dice_dataset` — feature range clamping, permitted-features filter, index preservation | 3 |
| `TestFormatStatement` | `_format_statement` — per change type (loan_amount, loan_term, employment_length), multiple changes, empty changes | 4 |

Total: **19 tests** added to existing file.

### PR P2-3: next_best_offer tests (~13 tests)

Target: lift `next_best_offer.py` from 13% to ≥70%. No prior test file.

| Test class | Coverage target | Approx tests |
|------------|-----------------|--------------|
| `TestGenerateMessaging` | `_generate_messaging` — success path, Claude error → fallback, empty offers | 3 |
| `TestFormatPrecalculatedOffers` | `_format_precalculated_offers` — empty, single offer, multi offer, offer ordering | 3 |
| `TestGenerateMarketingMessage` | `generate_marketing_message` — alternate entry point, denial-reason injection | 2 |
| `TestCustomerContext` | `_get_customer_context` — income buckets (low/mid/high), age groups, missing fields | 3 |
| `TestExtractToolResult` | `_extract_tool_result` — success extraction, malformed response → fallback | 2 |

Total: **13 tests**.

## Mocking strategy

### Claude API

All LLM calls mocked via the shared `mock_claude_response` fixture. Crafted response text drives specific branches in `_check_*` guardrails. Example:

```python
def test_patronising_language_detected(mock_claude_response):
    agent = MarketingAgent()
    resp = mock_claude_response("We simply want to help you...")
    with patch.object(agent.client, "messages") as m:
        m.create.return_value = resp
        result = agent.generate(application, nbo_result)
    assert result["guardrail_triggered"] == "patronising_language"
```

### ML predictions (CF engine)

Mock `_predict_prob` directly on the engine instance. Test each branch of binary-search convergence without loading XGBoost:

```python
def test_binary_search_converges_on_approval(cf_engine):
    cf_engine._predict_prob = MagicMock(side_effect=[0.3, 0.45, 0.55, 0.65])
    result = cf_engine._binary_search_feature(...)
    assert result["converged"] is True
```

### XGBoost pipeline

Mock at the `ModelVersion.get_active()` boundary. No real model loading. CF engine's `__init__` takes an injected `predictor` for testability — tests pass a `MagicMock()`.

### Database

Use `@pytest.mark.django_db` + factory fixtures. No fixtures from JSON. Applications created in test with `LoanApplicationFactory(**overrides)` (existing factory in `backend/tests/factories.py`).

## Coverage gate strategy

Staged bumps, one per PR, proven pattern from #64:

1. PR P2-1 merges → CI reports new baseline (e.g., 68.4%)
2. That PR's commit sets `--cov-fail-under=68` (`floor(measured) - 0.5`, rounded)
3. PR P2-2 merges on top → CI reports new baseline (e.g., 70.8%)
4. That PR sets `--cov-fail-under=70`
5. PR P2-3 merges → CI reports e.g. 72.3%
6. That PR sets `--cov-fail-under=72`

**Final expected gate: 71-73%.** Not 75%. This is decision B (honest measurement).

## Testing philosophy

- **TDD red-green-refactor** per test. Write the failing test, run it to see it fail, add the minimal production-side hook if needed, run to see green, commit.
- **One assertion target per test.** A test named `test_patronising_language_detected` asserts on that branch; does not also check email length, subject line, timestamps.
- **No `hypothesis` library** — user feedback memory flags flaky property-based tests. Use `pytest.mark.parametrize` for data variation.
- **Explicit mock boundaries** — mock at the Anthropic client boundary, not deeper. Mocking internal methods of the service itself is a smell (except `_predict_prob` which is a well-defined stable seam).
- **Each test file ≤ 500 LOC.** If it grows past that, split by concern.

## Risks

| Risk | Mitigation |
|------|------------|
| DiCE timing flakiness on CI | Use `pytest.mark.xfail(reason="DiCE timing-dependent")` for the single path that hits the 120s timeout. Existing CF tests use this pattern. |
| Mock-Claude SDK drift | Centralise in `conftest.py` fixture — one place to update if anthropic SDK shape changes. |
| Large marketing test file (>500 LOC) | Acceptable for PR-1 given natural cohesion (single class being tested); if it exceeds 600 LOC, split into `test_marketing_guardrails.py` + `test_marketing_fallback.py` in PR-1 itself. |
| Coverage doesn't hit 70% per module | Accept per decision B. Report the measured number honestly. If a module lands at 65%, fine — the gate reflects it. |
| Test-DB connection issues locally | Existing issue on Windows dev env; CI unaffected. Developer may need to run specific tests via Docker. Documented in CONTRIBUTING.md already. |

## Dependencies

No new production dependencies. No new test dependencies (pytest, pytest-mock, pytest-django, factory-boy all already in `requirements-dev.txt`).

## Open questions

None. All blocking decisions made during brainstorming (decisions A/B/C answered in clarifying questions).

## Post-merge audit

After all three PRs merge:

- `grep -rn "from unittest.mock import" backend/apps/agents/tests/ backend/apps/ml_engine/tests/` should show consistent mocking pattern across new files.
- CI on master should report backend coverage in the 71-74% range.
- `--cov-fail-under` in `test.yml` should equal `floor(measured) - 0.5`, rounded.
- CHANGELOG entry v1.9.2 documenting the phase 2 lift.
- `docs/reviews/2026-04-17-v1.9.1-review-response.md` "Phase 2" section updated with final measured coverage.
- Memory file `project_v1_9_1_review_response.md` updated: phase 2 → done, new target rating 9.5+.
