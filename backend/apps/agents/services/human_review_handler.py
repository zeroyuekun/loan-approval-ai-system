import logging
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.agents.exceptions import LLMServiceError
from apps.agents.metrics import bias_review_total, bias_review_ttr_seconds
from apps.agents.models import AgentRun
from apps.email_engine.services.decision_email import deliver_decision_email, generate_decision_email
from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.services.decision_explanation import ranked_denial_drivers
from apps.ml_engine.services.scoring.reason_codes import generate_adverse_action_reasons

from .api_budget import bind_api_call_context
from .bias.core import BiasDetector
from .bias.thresholds import is_severe
from .bias_records import bias_context, save_bias_report
from .context_builder import ApplicationContextBuilder
from .email_pipeline import build_denial_email_context, replace_flagged_email
from .marketing_pipeline import MarketingPipelineService
from .step_tracker import StepTracker

logger = logging.getLogger("agents.orchestrator")


def build_denial_reason_summary(shap_values: dict, feature_importances: dict) -> str:
    """Human-readable denial-reason summary for the marketing/NBO step.

    Uses the shared DecisionExplanation ranking + reason codes.
    """
    reasons = generate_adverse_action_reasons(shap_values or {}, "denied")
    if reasons:
        return "; ".join(r["reason"] for r in reasons)
    if feature_importances:
        drivers = ranked_denial_drivers(shap_values=shap_values or {}, feature_importances=feature_importances, max_n=3)
        return ", ".join(name.replace("_", " ") for name, _ in drivers)
    return ""


class HumanReviewHandler:
    """Handles resuming the pipeline after human review."""

    def __init__(self, step_tracker: StepTracker, context_builder: ApplicationContextBuilder):
        self.tracker = step_tracker
        self.context_builder = context_builder

    def resume_after_review(self, agent_run_id, reviewer="", note="", action="approve"):
        """Issue the decision on record after a reviewer approved or denied.

        Both outcomes take the same path: generate the decision email, run the
        bias pre-screen/check, deliver once, then apply the decision. For a
        deny the view has already written the denial onto the LoanDecision.
        """
        start_time = time.time()
        logger.info("Resuming agent run %s after human review", agent_run_id)

        with transaction.atomic():
            # `application.decision` is a nullable OneToOne. Including it in a
            # select_related alongside select_for_update produces a LEFT JOIN
            # that Postgres refuses to lock ("FOR UPDATE cannot be applied to
            # the nullable side of an outer join"). Fetch decision separately
            # below.
            agent_run = (
                AgentRun.objects.select_for_update().select_related("application__applicant").get(pk=agent_run_id)
            )

            # The review view claims the run (RUNNING) when it dispatches this
            # resume; ESCALATED is still accepted for direct callers.
            if agent_run.status not in ("escalated", "running"):
                raise ValueError(
                    f'Cannot resume agent run with status {agent_run.status!r} (expected "escalated" or "running")'
                )

            # Capture the escalation timestamp BEFORE we flip status, since
            # the save below will bump updated_at. Used for the bias-review
            # TTR histogram further down.
            escalated_at = agent_run.updated_at

            application = agent_run.application
            bind_api_call_context(application_id=application.pk)

            # Lock application to prevent two simultaneous reviews from resuming
            LoanApplication.objects.select_for_update().get(pk=application.pk)
            if application.status != "review":
                raise ValueError(f'Cannot resume: application status is {application.status!r} (expected "review")')

            try:
                decision = application.decision.decision
            except LoanDecision.DoesNotExist as err:
                raise ValueError(f"No decision found for application {application.id}") from err

            # Mark as running inside the lock to prevent duplicate resume
            agent_run.status = "running"
            agent_run.save(update_fields=["status"])

        # Refetch with profile outside the lock (nullable relation can't be in select_for_update)
        application = LoanApplication.objects.select_related("applicant__profile", "decision").get(pk=application.pk)
        profile_context = self.context_builder.build_profile_context(application)
        steps = agent_run.steps or []

        # Record the human outcome
        step = self.tracker.start_step("human_review_denied" if action == "deny" else "human_review_approved")
        step = self.tracker.complete_step(
            step,
            result_summary={
                "reviewer": reviewer,
                "note": note,
                "action": action,
            },
        )
        steps.append(step)

        # Decision email, for BOTH outcomes: regenerate (template fallback on
        # provider trouble or guardrail exhaustion), re-run the bias check the
        # original pipeline ran, then deliver once with sent_at stamped. A
        # denied run previously skipped this and sent only the marketing
        # follow-up, whose prompt assumes the customer already has the notice.
        email_context = profile_context
        if decision == "denied":
            email_context = build_denial_email_context(application, profile_context)

        step = self.tracker.start_step("email_generation")
        generated_email = None
        try:
            email_result, generated_email = generate_decision_email(
                application,
                decision,
                confidence=application.decision.confidence,
                profile_context=email_context,
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
            logger.error("Agent run %s: %s email generation failed: %s", agent_run_id, decision, e)
            step = self.tracker.fail_step(step, str(e), failure_category="transient")
            email_result = None
        except Exception as e:
            logger.critical(
                "Agent run %s: UNEXPECTED failure at %s email_generation: %s",
                agent_run_id,
                decision,
                e,
                exc_info=True,
            )
            step = self.tracker.fail_step(step, str(e), failure_category=None)
            email_result = None
        steps.append(step)

        # Guardrail failure on resume (the template failed too): withhold the
        # email and still apply the reviewer's decision, as the pipeline does.
        # Only bias findings go to the review queue.
        if email_result and not email_result.get("passed_guardrails"):
            failed_checks = [r["check_name"] for r in email_result.get("guardrail_results", []) if not r["passed"]]
            logger.warning(
                "Agent run %s: %s email guardrails failed on resume — email withheld. Failed checks: %s",
                agent_run_id,
                decision,
                ", ".join(failed_checks),
            )
            step = self.tracker.start_step("email_delivery")
            step = self.tracker.complete_step(
                step,
                result_summary={
                    "sent": False,
                    "reason": "Guardrails failed on resume — email withheld",
                    "failed_guardrails": failed_checks,
                },
            )
            steps.append(step)
            email_result = None  # nothing to bias-check or deliver

        # Re-run bias detection on the regenerated email. The original pipeline
        # ran bias detection before sending; the resume path must mirror this
        # check so a regenerated email cannot bypass bias screening by going
        # through the human-review flow.
        if email_result and email_result.get("passed_guardrails"):
            step_bias = self.tracker.start_step("bias_check_resume")
            try:
                bias_detector = BiasDetector()
                bias_result = bias_detector.analyze(email_result["body"], bias_context(application, decision))
                # Persist the report against the email, as the pipeline does,
                # so a withheld draft is identifiable as bias-held later.
                save_bias_report(agent_run, generated_email, bias_result)
                step_bias = self.tracker.complete_step(
                    step_bias,
                    result_summary={
                        "bias_score": bias_result["score"],
                        "flagged": bias_result["flagged"],
                    },
                )
                steps.append(step_bias)

                # A severe finding re-escalates, as in the pipeline. A moderate
                # one gets the template as a replacement, which is sent unless
                # it is severe too: a reviewer has already cleared this run, so
                # holding it again for a moderate score would loop it through
                # the review queue for good. The flagged LLM text never ships.
                held_reason = None
                review_threshold = getattr(settings, "BIAS_THRESHOLD_REVIEW", 60)
                if is_severe(bias_result["score"], review_threshold):
                    held_reason = f"Resumed email re-flagged by bias detector (score={bias_result['score']})"
                elif bias_result["flagged"]:
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
                            profile_context=email_context,
                        )
                    except Exception as exc:
                        # The flagged original must not ship, whatever BIAS_FAILURE_MODE says.
                        logger.error("Agent run %s: bias re-check of the replacement failed: %s", agent_run_id, exc)
                        replacement = None
                    if replacement is None or is_severe(replacement[2]["score"], review_threshold):
                        held_reason = (
                            f"Resumed email flagged by bias detector (score={bias_result['score']}) "
                            "and no sendable replacement"
                        )
                    else:
                        email_result, generated_email, bias_result = replacement

                if held_reason:
                    logger.warning(
                        "Agent run %s: %s — re-escalating application %s", agent_run_id, held_reason, application.id
                    )
                    step_hold = self.tracker.start_step("email_delivery")
                    step_hold = self.tracker.complete_step(
                        step_hold,
                        result_summary={
                            "sent": False,
                            "reason": "Bias detected on resume — re-escalating",
                        },
                    )
                    steps.append(step_hold)
                    with transaction.atomic():
                        application.refresh_from_db()
                        if application.status not in (
                            LoanApplication.Status.REVIEW,
                            LoanApplication.Status.PENDING,
                        ):
                            application.status = LoanApplication.Status.REVIEW
                            application.save(update_fields=["status"])
                    agent_run.status = "escalated"
                    agent_run.error = f"{held_reason} — re-escalated"
                    self.tracker.finalize_run(agent_run, steps, start_time)
                    return agent_run

            except Exception as exc:
                step_bias = self.tracker.fail_step(step_bias, str(exc), failure_category="transient")
                steps.append(step_bias)
                # BIAS_FAILURE_MODE as in the pipeline: warn/off fail open and
                # send. In block mode the email is withheld; the run goes back
                # to ESCALATED rather than to PENDING (the pipeline's hold) so
                # the reviewer's decision, already on record for a deny, stays
                # actionable from the queue it came from.
                mode = getattr(settings, "BIAS_FAILURE_MODE", "block").lower()
                if mode in ("warn", "off"):
                    logger.error(
                        "Agent run %s: bias check failed on resume — failing open (%s): %s", agent_run_id, mode, exc
                    )
                else:
                    logger.error("Agent run %s: bias check failed on resume — re-escalating: %s", agent_run_id, exc)
                    agent_run.status = "escalated"
                    agent_run.error = f"Bias check failed on resume — withheld for safety: {exc}"
                    self.tracker.finalize_run(agent_run, steps, start_time)
                    return agent_run

        # Send the decision email (once; stamps sent_at so a later standalone
        # generate/send for the same decision does not email the customer again).
        if email_result:
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
                logger.error("Agent run %s: %s email delivery failed: %s", agent_run_id, decision, e)
                step = self.tracker.fail_step(step, str(e), failure_category="transient")
            except Exception as e:
                logger.critical(
                    "Agent run %s: UNEXPECTED failure at %s email_delivery: %s",
                    agent_run_id,
                    decision,
                    e,
                    exc_info=True,
                )
                step = self.tracker.fail_step(step, str(e), failure_category=None)
            steps.append(step)

        # Apply the reviewer's decision before the follow-up below: the
        # customer may already have the decision email, and a follow-up failure
        # that put the run back in the review queue would send them a second
        # one on the next approve.
        with transaction.atomic():
            application.refresh_from_db()
            application.transition_to(
                decision,
                details={"source": "human_review_resume", "officer": reviewer or "", "note": note or ""},
            )
            # Record that a human was involved, so the ADM disclosure can
            # truthfully report "assisted" after status moves off 'review'.
            loan_decision = application.decision
            if loan_decision.human_involvement == LoanDecision.HumanInvolvement.NONE:
                loan_decision.human_involvement = LoanDecision.HumanInvolvement.ASSISTED
                loan_decision.save(update_fields=["human_involvement"])

        if decision == "denied":
            denial_reasons = ""
            try:
                denial_reasons = build_denial_reason_summary(
                    application.decision.shap_values,
                    application.decision.feature_importances,
                )
            except (LoanDecision.DoesNotExist, AttributeError) as exc:
                logger.debug(
                    "denial_feature_importances_missing",
                    extra={
                        "agent_run_id": str(agent_run_id),
                        "application_id": str(application.id),
                        "error": type(exc).__name__,
                    },
                )

            # Best-effort, as in the pipeline: the decision is applied and
            # announced, so a failure here (including the soft time limit) is
            # recorded and the run still completes.
            try:
                marketing_pipeline = MarketingPipelineService(self.tracker)
                steps = marketing_pipeline.run(
                    application,
                    agent_run,
                    steps,
                    denial_reasons,
                    profile_context,
                )
            except Exception as exc:  # noqa: BLE001 — post-decision follow-up is best-effort
                logger.error("Agent run %s: NBO/marketing follow-up failed after the decision: %s", agent_run_id, exc)
                steps.append(StepTracker.post_decision_failure_step("marketing_followup", exc))

        # Finalize — finalize_run sets status to 'completed' internally
        self.tracker.finalize_run(agent_run, steps, start_time)

        # Emit time-to-resolution for the bias review queue (docs/slo.md).
        try:
            ttr = (timezone.now() - escalated_at).total_seconds()
            bias_review_ttr_seconds.labels(decision=decision).observe(ttr)
            bias_review_total.labels(outcome="human_resolved").inc()
        except Exception as exc:  # noqa: BLE001 — best-effort metric
            logger.debug("bias_review_ttr emission failed: %s", exc)

        logger.info("Agent run %s: resumed and completed with decision=%s", agent_run_id, decision)

        return agent_run
