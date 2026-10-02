# Second Bias Agent and Offers in Denial Emails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A decision email flagged in the moderate bias band is rewritten by a second agent and checked more strictly before the template fallback, and every denial email carries the next-best offer.

**Architecture:** A new module `agents/services/bias_agent2.py` runs the rewrite and the stricter check. The pipeline calls it before the existing `replace_flagged_email` template path. If Agent 2 returns nothing, the pipeline falls through to that path unchanged. The offer block moves to a shared renderer in `template_fallback.py`, so the LLM prompt and the template use the same text. `bias_context` and `save_bias_report` move to `agents/services/bias_records.py` so both modules can import them without a cycle.

**Tech Stack:** Django 5, pytest, Anthropic SDK (through the existing `guarded_api_call` budget funnel).

**Spec:** `docs/superpowers/specs/2026-10-02-agent-pipeline-completeness-design.md` (sections A and B)

## Global Constraints

- Never add "apologise", "sorry" or "disappointment" to email prompts or templates.
- Only bias findings route to human review.
- `BIAS_AGENT2_ENABLED` defaults to true. When it is false, behaviour is identical to PR #275.
- Senior reviewer approval needs `approved=True` and `confidence >= 0.70`.
- Backend tests run in a dev-stage container built from this worktree. See the "Testing a git worktree" note in the project memory. Run one test container at a time.
- Run ruff on the host before each commit: `cd backend && ruff check apps tests && ruff format apps tests`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

Test command used below (written `PYTEST <args>`):

```bash
docker run --rm --network loan-approval-ai-system_internal --env-file "$SCRATCH/backend.env" \
  -v "C:/Users/Admin/loan-wt-agents/backend:/app" -w /app --entrypoint bash loan-backend:devtest \
  -lc "python -m pytest <args> -q"
```

---

### Task 1: Move the bias record helpers into their own module

**Files:**
- Create: `backend/apps/agents/services/bias_records.py`
- Modify: `backend/apps/agents/services/email_pipeline.py` (delete the two function bodies and import them from the new module, so `from .email_pipeline import bias_context, save_bias_report` keeps working)

**Interfaces:**
- Produces: `bias_context(application, decision) -> dict` and `save_bias_report(agent_run, generated_email, bias_result) -> BiasReport`. Same behaviour as today.

- [ ] Step 1: Create `bias_records.py`, containing the two functions moved verbatim (with a module docstring and the `BiasReport` import).
- [ ] Step 2: In `email_pipeline.py`, replace the definitions with `from .bias_records import bias_context, save_bias_report  # noqa: F401 - re-exported`.
- [ ] Step 3: Run `PYTEST tests/test_bias_moderate_band.py tests/test_resume_pipeline.py apps/agents/tests/test_bias_failsafe.py`. Expected: all pass, with no behaviour change.
- [ ] Step 4: Commit `refactor(agents): bias record helpers in their own module`.

### Task 2: Bias feedback in the email generator

**Files:**
- Modify: `backend/apps/email_engine/services/email_generator.py`. `generate()` gets a `bias_feedback=None` keyword. It is passed through the recursive retry and appended to the prompt.
- Modify: `backend/apps/email_engine/services/decision_email.py`. Add `regenerate_decision_email`.
- Test: `backend/tests/test_bias_agent2.py` (new)

**Interfaces:**
- Produces: `EmailGenerator.generate(application, decision, attempt=1, confidence=None, profile_context=None, bias_feedback=None)`
- Produces: `regenerate_decision_email(application, decision, *, confidence, profile_context, bias_feedback, generator=None) -> tuple[dict, GeneratedEmail | None]`. `RateLimited` propagates to the caller. A result with `template_fallback=True` is returned with `None` and is NOT persisted, because the template path makes its own.

- [ ] Step 1: Write the failing tests:

```python
@pytest.mark.django_db
def test_bias_feedback_reaches_the_prompt(processing_denied):
    gen = EmailGenerator()
    captured = {}

    def fake_call(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        raise RuntimeError("stop after prompt build")

    with patch.object(gen, "client", MagicMock()), patch(
        "apps.email_engine.services.email_generator.guarded_api_call", side_effect=lambda client, **kw: fake_call(**kw)
    ):
        try:
            gen.generate(processing_denied, "denied", bias_feedback="tone_check: labels the person")
        except Exception:
            pass
    assert "COMPLIANCE REVIEW FEEDBACK" in captured["prompt"]
    assert "tone_check: labels the person" in captured["prompt"]


@pytest.mark.django_db
def test_regenerate_does_not_persist_a_template_result(processing_denied):
    from apps.email_engine.services.decision_email import regenerate_decision_email

    gen = MagicMock()
    gen.generate.return_value = {**_llm_email(), "template_fallback": True}
    result, generated = regenerate_decision_email(
        processing_denied, "denied", confidence=0.2, profile_context={}, bias_feedback="x", generator=gen
    )
    assert generated is None
    assert not GeneratedEmail.objects.filter(application=processing_denied).exists()
```

(Adapt the patch target to whatever `generate()` actually calls for the API request: read the call site first. The assertion that matters is that the feedback text is in the prompt sent.)

- [ ] Step 2: Run the tests. Expected: FAIL. `generate()` has no `bias_feedback`, and `regenerate_decision_email` is missing.
- [ ] Step 3: Implement. In `generate()`, after the denial/approval prompt is built and before the retry-feedback block:

```python
        if bias_feedback:
            prompt += (
                "\n\n=== COMPLIANCE REVIEW FEEDBACK ===\n"
                "A compliance reviewer flagged an earlier draft of this email for possible bias:\n"
                f"{_sanitize_prompt_input(bias_feedback, max_length=2000)}\n\n"
                "Write the email again so none of these issues appear. Describe the application and "
                "its circumstances, never the person. Keep every required section.\n"
            )
```

Pass `bias_feedback=bias_feedback` in the recursive `self.generate(...)` call. In `decision_email.py`:

```python
def regenerate_decision_email(application, decision, *, confidence, profile_context, bias_feedback, generator=None):
    """Second-agent rewrite of a bias-flagged email. Returns ``(result, generated_email)``.

    A template result (LLM unavailable, budget gate, guardrail exhaustion) is
    returned with ``None`` and not persisted: the caller hands over to the
    template replacement path, which persists its own template. RateLimited
    propagates.
    """
    generator = generator or EmailGenerator()
    result = generator.generate(
        application, decision, confidence=confidence, profile_context=profile_context, bias_feedback=bias_feedback
    )
    if result.get("template_fallback"):
        return result, None
    return result, _persist(application, decision, result)
```

- [ ] Step 4: Run the tests. Expected: PASS.
- [ ] Step 5: Commit `feat(email): generator accepts bias-review feedback for a second-agent rewrite`.

### Task 3: The Agent 2 module

**Files:**
- Create: `backend/apps/agents/services/bias_agent2.py`
- Modify: `backend/config/settings/base.py`. Add `BIAS_AGENT2_ENABLED = os.environ.get("BIAS_AGENT2_ENABLED", "true").lower() == "true"` and `BIAS_AGENT2_MIN_REVIEWER_CONFIDENCE = 0.70`, next to the other `BIAS_*` settings.
- Test: `backend/tests/test_bias_agent2.py`

**Interfaces:**
- Consumes: `regenerate_decision_email` (Task 2), and `bias_context` and `save_bias_report` (Task 1).
- Produces: `run_agent2(application, agent_run, decision, email_result, bias_result, *, confidence, profile_context, tracker, steps) -> tuple[dict, GeneratedEmail, dict] | None`. A tuple means "send this". `None` means "hand over to the template path".

- [ ] Step 1: Write the failing unit tests for `run_agent2`:
  - It returns `None` without calling the generator when disabled.
  - It returns `None` without calling the generator when `email_result["template_fallback"]` is set.
  - It returns `None` when the regenerated result is a template.
  - It returns `None` when the regenerated result fails guardrails.
  - It returns `None` when the detector flags the new text.
  - It returns `None` when the reviewer gives `approved=False`.
  - It returns `None` when the reviewer approves with confidence 0.5.
  - It returns `None` when the generator raises `RateLimited` or any exception.
  - It returns the tuple when the detector is clean and the reviewer approves at 0.9.
  - Each case except "disabled" and "template original" records exactly one `bias_agent2_regeneration` step.
  - A `BiasReport` is saved for the new email.
  - The reviewer gets the new email's body.

  Patch `apps.agents.services.bias_agent2.regenerate_decision_email`, `apps.agents.services.bias_agent2.BiasDetector` and `apps.agents.services.bias_agent2.AIEmailReviewer`. Give mocks concrete leaf values, never bare MagicMocks that reach JSON fields (observation 0053).
- [ ] Step 2: Run the tests. Expected: FAIL with `ModuleNotFoundError: apps.agents.services.bias_agent2`.
- [ ] Step 3: Implement:

```python
"""Agent 2: rewrite a moderate-band bias-flagged decision email and check it more strictly.

The first bias check flagged the email but scored it below the human-review
threshold. Agent 2 asks the email generator for a new draft with the findings
as feedback, then requires two independent passes before the new draft may be
sent: the bias detector must not flag it, and the senior compliance reviewer
(a stronger model with a different mandate) must approve it with confidence.
Anything else hands over to the deterministic template path, so Agent 2 can
only replace an email with one that passed more checks, never weaken the flow.
"""

import logging

from django.conf import settings

from apps.email_engine.services.decision_email import regenerate_decision_email

from .bias.reviewer import AIEmailReviewer
from .bias_detector import BiasDetector
from .bias_records import bias_context, save_bias_report

logger = logging.getLogger("agents.orchestrator")

STEP_NAME = "bias_agent2_regeneration"


def _feedback(bias_result):
    categories = ", ".join(bias_result.get("categories") or []) or "unspecified"
    return f"Flagged categories: {categories}. Reviewer analysis: {bias_result.get('analysis', '')}"


def run_agent2(
    application, agent_run, decision, email_result, bias_result, *, confidence, profile_context, tracker, steps
):
    """Return ``(email_result, generated_email, bias_result)`` to send, or None to hand over."""
    if not getattr(settings, "BIAS_AGENT2_ENABLED", True) or email_result.get("template_fallback"):
        return None

    step = tracker.start_step(STEP_NAME)

    def hand_over(reason, **extra):
        steps.append(tracker.complete_step(step, result_summary={"regenerated": False, "reason": reason, **extra}))
        logger.info("Application %s: Agent 2 handed over to the template path: %s", application.pk, reason)
        return None

    try:
        result, generated_email = regenerate_decision_email(
            application,
            decision,
            confidence=confidence,
            profile_context=profile_context,
            bias_feedback=_feedback(bias_result),
        )
        if generated_email is None:
            return hand_over("The LLM was unavailable, so no rewrite was written")
        if not result.get("passed_guardrails"):
            return hand_over("The rewrite failed its guardrails")

        context = bias_context(application, decision)
        new_bias = BiasDetector().analyze(result["body"], context)
        save_bias_report(agent_run, generated_email, new_bias)
        if new_bias.get("flagged"):
            return hand_over("The bias check flagged the rewrite", bias_score=new_bias.get("score"))

        review = AIEmailReviewer().review(result["body"], new_bias, context)
        min_confidence = getattr(settings, "BIAS_AGENT2_MIN_REVIEWER_CONFIDENCE", 0.70)
        approved = bool(review.get("approved")) and float(review.get("confidence") or 0.0) >= min_confidence
        if not approved:
            return hand_over(
                "The senior reviewer did not approve the rewrite",
                bias_score=new_bias.get("score"),
                reviewer_approved=bool(review.get("approved")),
                reviewer_confidence=review.get("confidence"),
            )
    except Exception as exc:  # noqa: BLE001 - every failure hands over to the template path
        logger.warning("Application %s: Agent 2 failed: %s", application.pk, exc)
        return hand_over(f"Agent 2 failed: {type(exc).__name__}")

    steps.append(
        tracker.complete_step(
            step,
            result_summary={
                "regenerated": True,
                "previous_score": bias_result.get("score"),
                "bias_score": new_bias.get("score"),
                "flagged": False,
                "reviewer_approved": True,
                "reviewer_confidence": review.get("confidence"),
            },
        )
    )
    return result, generated_email, new_bias
```

- [ ] Step 4: Run the tests. Expected: PASS.
- [ ] Step 5: Commit `feat(agents): Agent 2 rewrites a moderate-band flagged email under a stricter check`.

### Task 4: Wire Agent 2 into the pipeline

**Files:**
- Modify: `backend/apps/agents/services/email_pipeline.py`, in the moderate-band branch of `EmailPipelineService.run`.
- Modify: `backend/tests/test_bias_moderate_band.py`. The existing pipeline tests pin the template path, so mark them `@override_settings(BIAS_AGENT2_ENABLED=False)`. Their guard (a flagged email never ships as written) still holds. Add pipeline-level tests with Agent 2 on.

**Interfaces:**
- Consumes: `run_agent2` (Task 3).

- [ ] Step 1: Write the failing pipeline tests. Use `_run_pipeline`, extended with patches for `apps.agents.services.bias_agent2.BiasDetector` and `apps.agents.services.bias_agent2.AIEmailReviewer`, and with `EmailGenerator.generate` side effects returning a first and a second email body.
  - The rewrite is clean and approved: it is sent, the waterfall has `EMAIL_REGENERATED_AGENT2`, the sent body is the rewrite, and the flagged draft is never sent.
  - The reviewer rejects: the template is sent (template re-check clean).
  - The reviewer rejects and the template is flagged: escalated to review.
- [ ] Step 2: Run the tests. Expected: FAIL. The rewrite is never attempted, so the template is sent.
- [ ] Step 3: Implement. In `run()`, inside `if bias_result.get("flagged"):` and before the `replace_flagged_email` try:

```python
            agent2 = run_agent2(
                application,
                agent_run,
                decision,
                email_result,
                bias_result,
                confidence=prediction_result["probability"],
                profile_context=profile_context,
                tracker=self.tracker,
                steps=steps,
            )
            if agent2 is not None:
                email_result, generated_email, bias_result = agent2
                waterfall.append(
                    StepTracker.waterfall_entry(
                        "bias_regeneration",
                        "pass",
                        "EMAIL_REGENERATED_AGENT2",
                        f"Flagged email (score {bias_score}) rewritten by Agent 2; the rewrite passed the bias "
                        f"check (score {bias_result.get('score', 0)}) and the senior review",
                    )
                )
```

Then wrap the existing template block in `else:` (dedent-safe: `if agent2 is None:`). Import `from .bias_agent2 import run_agent2`.
- [ ] Step 4: Run `PYTEST tests/test_bias_moderate_band.py tests/test_bias_agent2.py tests/test_orchestrator.py tests/test_resume_pipeline.py apps/agents/tests`. Expected: all PASS.
- [ ] Step 5: Update `workflows/bias_detection.md` with the moderate-band route, so the WAT workflow stays current.
- [ ] Step 6: Commit `feat(agents): moderate bias band tries Agent 2 before the template`.

### Task 5: Shared offer renderer and an offer in template denials (PR B)

Create the branch `feat/denial-template-offer` from the Task 4 commit before starting.

**Files:**
- Modify: `backend/apps/email_engine/services/template_fallback.py`. Add `render_nbo_block(nbo_offer) -> str`, moved from `EmailGenerator._render_nbo_block`. `generate_denial_template(..., nbo_offer=None)` inserts the block under "We'd Still Like to Help:".
- Modify: `backend/apps/email_engine/services/email_generator.py`. `_render_nbo_block` delegates. `_add_nbo_context(context, nbo_offer)` is shared by the LLM and template paths. `generate_template(application, decision, profile_context=None)`. `_generate_fallback` reads the offer from `context.get("nbo_offers")`.
- Modify: `backend/apps/email_engine/services/decision_email.py`. `generate_template_decision_email(..., profile_context=None)`, and the rate-limit fallback passes `profile_context`.
- Modify: `backend/apps/agents/services/email_pipeline.py`. `replace_flagged_email(..., profile_context=None)` passes it through. The pipeline passes `profile_context`. The human-review resume caller passes the denial context it already builds.
- Test: `backend/apps/email_engine/tests/test_template_offer.py` (new)

- [ ] Step 1: Write the failing tests:
  - `generate_denial_template(..., nbo_offer=OFFER)` contains `render_nbo_block(OFFER)`, and without an offer contains no "A specific option".
  - `EmailGenerator().generate_template(app, "denied", profile_context={"nbo_offer": OFFER})` passes guardrails, and the body has the offer amount.
  - `generate_template(app, "approved", profile_context={"nbo_offer": OFFER})` has no offer.
  - `EmailGenerator()._render_nbo_block(OFFER) == render_nbo_block(OFFER)`.
  - The banned words "sorry", "apologise" and "disappointment" are absent from the rendered block.

  Use `OFFER = {"name": "Personal Loan", "type": "personal", "amount": 15000, "estimated_rate": 9.99, "monthly_repayment": 320}`, and check against the real RecommendationEngine offer keys before relying on them.
- [ ] Step 2: Run the tests. Expected: FAIL. `render_nbo_block` is missing and the `nbo_offer` keyword is unknown.
- [ ] Step 3: Implement as described. In the template body, put `{offer_text}` before "If a different loan product…", where `offer_text = f"{block}\n\n" if block else ""`.
- [ ] Step 4: Run `PYTEST apps/email_engine tests/test_bias_moderate_band.py tests/test_bias_agent2.py tests/test_resume_pipeline.py`. Expected: PASS. If email snapshot or parity tests exist for the denial template, they must still pass unchanged, because their fixtures carry no offer.
- [ ] Step 5: Commit `feat(email): denial template carries the next-best offer`.

### Task 6: Verify and hand off

- [ ] Run the full backend suite once in the worktree container, ignoring the two hypothesis files.
- [ ] Run `ruff check` and `ruff format --check` on the host.
- [ ] Record the results for the PR bodies. Do not push: pushing and opening PRs wait for the user's approval.
