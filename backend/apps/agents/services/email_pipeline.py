import logging

from django.conf import settings
from django.db import transaction

from apps.agents.exceptions import LLMServiceError
from apps.agents.metrics import bias_check_unavailable_total
from apps.email_engine.services.decision_email import (
    deliver_decision_email,
    generate_decision_email,
    generate_template_decision_email,
)
from apps.loans.models import LoanApplication

from .bias.thresholds import is_severe
from .bias_agent2 import run_agent2
from .bias_detector import BiasDetector
from .bias_records import bias_context, save_bias_report
from .recommendation_engine import RecommendationEngine
from .step_tracker import StepTracker

logger = logging.getLogger("agents.orchestrator")


def build_denial_email_context(application, profile_context):
    """Add the deterministic alternative-offer teaser to a denial email's context.

    RecommendationEngine makes NO API call, so this adds no cost, and it must
    never block the decision email: on error the email goes out without a
    teaser. Shared by the orchestrator and the human-review resume path.
    """
    try:
        nbo = RecommendationEngine().recommend(application, denial_reasons="")
        offers = nbo.get("offers") or []
        if offers:
            return {**(profile_context or {}), "nbo_offer": offers[0]}
    except Exception as exc:  # noqa: BLE001 — teaser is best-effort
        logger.warning("Application %s: NBO teaser unavailable: %s", application.pk, exc)
    return profile_context


def replace_flagged_email(
    application,
    agent_run,
    decision,
    email_result,
    generated_email,
    bias_result,
    detector,
    tracker,
    steps,
    profile_context=None,
):
    """Swap a moderate-band flagged email for the template and bias-check the template.

    A flagged LLM email is never sent as written. This is the fallback when
    Agent 2's rewrite was skipped or handed over. Generating the deterministic
    template costs no API call; its bias re-check can still call the LLM when
    the pre-screen finds something ambiguous. Returns the template as
    ``(email_result, generated_email, bias_result)``, with its own bias result,
    so the caller decides whether it may be sent. A flagged email that already
    is the template comes back unchanged, because regenerating it gives the
    same text. Returns None when the template failed its guardrails. Exceptions
    from the bias check propagate after the step is recorded. ``profile_context``
    carries ``nbo_offer`` for denials, so the replacement template still carries
    the next-best offer.
    """
    step = tracker.start_step("bias_regeneration")
    if email_result.get("template_fallback"):
        steps.append(
            tracker.complete_step(
                step, result_summary={"replaced": False, "reason": "The flagged email is already the template"}
            )
        )
        return email_result, generated_email, bias_result
    try:
        result, generated_email = generate_template_decision_email(
            application, decision, profile_context=profile_context
        )
        if not result.get("passed_guardrails"):
            steps.append(
                tracker.complete_step(
                    step, result_summary={"replaced": False, "reason": "The template failed its guardrails"}
                )
            )
            return None
        new_bias = detector.analyze(result["body"], bias_context(application, decision))
        save_bias_report(agent_run, generated_email, new_bias)
    except Exception as exc:
        steps.append(tracker.fail_step(step, str(exc), failure_category="transient"))
        raise
    steps.append(
        tracker.complete_step(
            step,
            result_summary={
                "replaced": True,
                "previous_score": bias_result.get("score"),
                "bias_score": new_bias["score"],
                "flagged": new_bias["flagged"],
            },
        )
    )
    return result, generated_email, new_bias


class EmailPipelineService:
    """Handles email generation, bias detection, and delivery for the pipeline."""

    def __init__(self, step_tracker: StepTracker):
        self.tracker = step_tracker

    def run(self, application, agent_run, profile_context, prediction_result, decision, steps, waterfall):
        """Run email generation + bias check + delivery.

        Returns (steps, email_result, generated_email, bias_result, escalated).
        If escalated is True, the caller should return agent_run immediately.
        """
        application_id = application.pk
        email_result = None
        generated_email = None

        if decision == "denied":
            profile_context = build_denial_email_context(application, profile_context)

        # Step 2: Generate Email (template fallback on provider errors, budget
        # gate, guardrail exhaustion and 429 — see decision_email).
        step = self.tracker.start_step("email_generation")
        try:
            email_result, generated_email = generate_decision_email(
                application,
                decision,
                confidence=prediction_result["probability"],
                profile_context=profile_context,
            )

            email_status = "pass" if email_result["passed_guardrails"] else "fail"
            waterfall.append(
                StepTracker.waterfall_entry(
                    "email_generation",
                    email_status,
                    "EMAIL_GENERATED",
                    f"Email generated (guardrails_passed={email_result['passed_guardrails']}, "
                    f"template_fallback={email_result.get('template_fallback', False)})",
                )
            )

            step = self.tracker.complete_step(
                step,
                result_summary={
                    "subject": email_result["subject"],
                    "passed_guardrails": email_result["passed_guardrails"],
                    "template_fallback": email_result.get("template_fallback", False),
                },
            )
        except (LLMServiceError, ConnectionError, TimeoutError) as e:
            logger.error("Application %s: email generation failed: %s", application_id, e)
            waterfall.append(
                StepTracker.waterfall_entry(
                    "email_generation",
                    "fail",
                    "EMAIL_ERROR",
                    f"Email generation failed: {e}",
                )
            )
            StepTracker.save_waterfall(application, waterfall)
            step = self.tracker.fail_step(step, str(e), failure_category="transient")
            steps.append(step)
            return steps, None, None, None, False
        except Exception as e:
            logger.critical(
                "Application %s: UNEXPECTED failure at email_generation: %s", application_id, e, exc_info=True
            )
            waterfall.append(
                StepTracker.waterfall_entry(
                    "email_generation",
                    "fail",
                    "EMAIL_ERROR",
                    f"Email generation unexpected failure: {e}",
                )
            )
            StepTracker.save_waterfall(application, waterfall)
            step = self.tracker.fail_step(step, str(e), failure_category=None)
            steps.append(step)
            return steps, None, None, None, False

        steps.append(step)

        # Step 3: Bias Check
        step = self.tracker.start_step("bias_check")
        try:
            bias_detector = BiasDetector()
            bias_result = bias_detector.analyze(email_result["body"], bias_context(application, decision))
            save_bias_report(agent_run, generated_email, bias_result)

            step = self.tracker.complete_step(
                step,
                result_summary={
                    "bias_score": bias_result["score"],
                    "flagged": bias_result["flagged"],
                },
            )
        except (LLMServiceError, ConnectionError, TimeoutError) as e:
            logger.error("Application %s: bias check failed: %s", application_id, e)
            step = self.tracker.fail_step(step, str(e), failure_category="transient")
            steps.append(step)  # always record the failed bias step before delegating
            held = self._handle_bias_unavailable(application, agent_run, steps, step, waterfall, e)
            if held is not None:
                return held
            bias_result = self._legacy_failopen_bias_result(e)
        except Exception as e:
            logger.critical("Application %s: UNEXPECTED failure at bias_check: %s", application_id, e, exc_info=True)
            step = self.tracker.fail_step(step, str(e), failure_category=None)
            steps.append(step)  # always record the failed bias step before delegating
            held = self._handle_bias_unavailable(application, agent_run, steps, step, waterfall, e)
            if held is not None:
                return held
            bias_result = self._legacy_failopen_bias_result(e)

        else:
            steps.append(step)

        # Waterfall entry for bias check
        bias_flagged = bias_result.get("flagged", False)
        waterfall.append(
            StepTracker.waterfall_entry(
                "bias_check",
                "fail" if bias_flagged else "pass",
                "BIAS_FLAGGED" if bias_flagged else "BIAS_CLEAR",
                f"Bias score={bias_result.get('score', 0)}, flagged={bias_flagged}",
            )
        )

        # Step 4: Handle bias results
        bias_score = bias_result.get("score", 0)
        bias_threshold_review = getattr(settings, "BIAS_THRESHOLD_REVIEW", 60)

        # Bias score at/above review threshold — escalate to human review.
        # Inclusive bound: a score equal to the threshold must escalate.
        if is_severe(bias_score, bias_threshold_review):
            self._escalate_for_bias(
                application,
                agent_run,
                steps,
                waterfall,
                code="ESCALATED_SEVERE_BIAS",
                step_name="human_escalation_severe_bias",
                reason=f"Severe bias detected (score {bias_score} >= {bias_threshold_review})",
                bias_score=bias_score,
            )
            return steps, email_result, generated_email, bias_result, True

        # Moderate band: flagged, below the severe threshold. The flagged email
        # is never sent. Agent 2 tries a rewrite first (sent only if the bias
        # check is clean and the senior reviewer approves it); if it hands over,
        # the template replaces the email and is sent only if it checks clean.
        # Otherwise the application is held for human review.
        if bias_result.get("flagged"):
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
                        "bias_agent2_regeneration",
                        "pass",
                        "EMAIL_REGENERATED_AGENT2",
                        f"Flagged email (score {bias_score}) rewritten by Agent 2; the rewrite passed the bias "
                        f"check (score {bias_result.get('score', 0)}) and the senior review",
                    )
                )
            else:
                try:
                    replacement = replace_flagged_email(
                        application,
                        agent_run,
                        decision,
                        email_result,
                        generated_email,
                        bias_result,
                        bias_detector,
                        self.tracker,
                        steps,
                        profile_context=profile_context,
                    )
                except Exception as e:
                    # The flagged original must not ship, so a failed re-check holds
                    # the run for review in every BIAS_FAILURE_MODE.
                    logger.error("Application %s: bias re-check of the replacement failed: %s", application_id, e)
                    replacement = None
                if replacement is None or replacement[2].get("flagged"):
                    self._escalate_for_bias(
                        application,
                        agent_run,
                        steps,
                        waterfall,
                        code="ESCALATED_MODERATE_BIAS",
                        step_name="human_escalation_moderate_bias",
                        reason=f"Bias flagged (score {bias_score}) and no clean replacement email",
                        bias_score=bias_score,
                    )
                    return steps, email_result, generated_email, bias_result, True
                email_result, generated_email, bias_result = replacement
                waterfall.append(
                    StepTracker.waterfall_entry(
                        "bias_regeneration",
                        "pass",
                        "EMAIL_REPLACED",
                        f"Flagged email (score {bias_score}) replaced by the template, which checked clean "
                        f"(score {bias_result.get('score', 0)})",
                    )
                )

        # Guardrail failure — log it and skip email delivery, but do NOT
        # escalate to human review.  Only bias flags trigger escalation.
        if email_result and not email_result["passed_guardrails"]:
            failed_checks = [r["check_name"] for r in email_result.get("guardrail_results", []) if not r["passed"]]
            waterfall.append(
                StepTracker.waterfall_entry(
                    "final_decision",
                    "warn",
                    "GUARDRAIL_FAILURE",
                    f"Email guardrails failed ({', '.join(failed_checks)}), email not sent",
                )
            )
            StepTracker.save_waterfall(application, waterfall)

            logger.warning(
                "Application %s: guardrails failed after %d attempts — email not sent. Failed checks: %s",
                application_id,
                email_result.get("attempt_number", 1),
                ", ".join(failed_checks),
            )
            step = self.tracker.start_step("email_delivery")
            step = self.tracker.complete_step(
                step,
                result_summary={
                    "sent": False,
                    "reason": "Guardrails failed — email withheld",
                    "failed_guardrails": failed_checks,
                },
            )
            steps.append(step)
            agent_run.error = f"Email guardrails failed: {', '.join(failed_checks)}"
            # Fall through to normal completion instead of escalating

        elif email_result and email_result["passed_guardrails"]:
            # Send decision email to customer (only when guardrails passed).
            # deliver_decision_email sends once under a row lock and stamps
            # sent_at, so the standalone task's redelivery path cannot re-send.
            step = self.tracker.start_step("email_delivery")
            try:
                outcome = deliver_decision_email(generated_email)
                if outcome["sent"] or outcome["already_sent"]:
                    step = self.tracker.complete_step(
                        step, result_summary={"sent": True, "recipient": outcome["recipient"]}
                    )
                elif outcome["recipient"] is None:
                    step = self.tracker.complete_step(
                        step, result_summary={"sent": False, "reason": "No recipient email"}
                    )
                else:
                    step = self.tracker.fail_step(step, outcome["error"] or "Send failed")
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.error("Application %s: email delivery failed: %s", application_id, e)
                step = self.tracker.fail_step(step, str(e), failure_category="transient")
            except Exception as e:
                logger.critical(
                    "Application %s: UNEXPECTED failure at email_delivery: %s", application_id, e, exc_info=True
                )
                step = self.tracker.fail_step(step, str(e), failure_category=None)
            steps.append(step)

        return steps, email_result, generated_email, bias_result, False

    def _escalate_for_bias(self, application, agent_run, steps, waterfall, *, code, step_name, reason, bias_score):
        """Withhold the email and put the application in the human-review queue."""
        waterfall.append(
            StepTracker.waterfall_entry("final_decision", "fail", code, f"{reason}, escalated to human review")
        )
        StepTracker.save_waterfall(application, waterfall)

        step = self.tracker.start_step(step_name)
        steps.append(
            self.tracker.complete_step(
                step, result_summary={"bias_score": bias_score, "reason": f"{reason}, escalated to human reviewer"}
            )
        )
        logger.warning("Application %s: %s, escalating", application.pk, reason)

        step = self.tracker.start_step("human_review_required")
        steps.append(
            self.tracker.complete_step(step, result_summary={"review_category": "bias_escalation", "reason": reason})
        )

        with transaction.atomic():
            application.refresh_from_db()
            application.transition_to(
                LoanApplication.Status.REVIEW,
                details={"source": "email_pipeline_bias_escalation", "bias_score": bias_score},
            )
        agent_run.status = "escalated"

    @staticmethod
    def _legacy_failopen_bias_result(exc):
        """Legacy fail-OPEN substitute (only used in BIAS_FAILURE_MODE in {warn, off})."""
        return {
            "score": 25,
            "flagged": False,
            "requires_human_review": False,
            "categories": [],
            "analysis": f"Bias check infrastructure error: {exc}",
        }

    def _handle_bias_unavailable(self, application, agent_run, steps, step, waterfall, exc):
        """Apply the BIAS_FAILURE_MODE policy when the bias check could not run.

        Returns the orchestrator tuple to HOLD the pipeline (block mode), or
        None to proceed fail-open (warn/off modes). Never auto-ships a decision
        with bias detection effectively off.
        """
        mode = getattr(settings, "BIAS_FAILURE_MODE", "block").lower()
        if mode not in ("block", "warn", "off"):
            logger.warning("Unknown BIAS_FAILURE_MODE=%r — defaulting to 'block'", mode)
            mode = "block"

        bias_check_unavailable_total.labels(mode=mode).inc()

        if mode != "block":
            # warn/off: alert recorded above; proceed with legacy fail-open.
            return None

        # block: FAIL-SAFE — withhold the email, roll back to PENDING for retry,
        # mark the run failed. Do NOT enter the bias human-review queue (an infra
        # failure is not a bias finding) and do NOT auto-apply the decision.
        waterfall.append(
            StepTracker.waterfall_entry(
                "final_decision",
                "fail",
                "BIAS_CHECK_UNAVAILABLE",
                f"Bias check could not run ({exc}) — email withheld, application held for retry "
                "(BIAS_FAILURE_MODE=block)",
            )
        )
        StepTracker.save_waterfall(application, waterfall)

        hold = self.tracker.start_step("email_delivery")
        hold = self.tracker.complete_step(
            hold,
            result_summary={
                "sent": False,
                "reason": "Bias check unavailable — fail-safe withhold (BIAS_FAILURE_MODE=block)",
            },
        )
        # Note: the failed bias step was already appended by the caller before
        # invoking this method.  Only append the email_delivery hold step here.
        steps.append(hold)

        with transaction.atomic():
            application.refresh_from_db()
            if application.status == LoanApplication.Status.PROCESSING:
                application.transition_to(
                    LoanApplication.Status.PENDING,
                    details={"source": "email_pipeline_bias_unavailable"},
                )
        agent_run.status = "failed"
        agent_run.failure_category = "transient"
        agent_run.error = f"Bias check unavailable — decision withheld (fail-safe): {exc}"
        logger.critical(
            "Application %s: bias check unavailable — fail-safe HOLD (email withheld, status->pending)",
            application.pk,
        )
        # escalated=True signals the orchestrator to finalize-and-return without
        # generating/sending a decision email or applying the decision.
        return steps, None, None, None, True
