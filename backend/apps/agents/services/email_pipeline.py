import logging

from django.conf import settings
from django.db import transaction

from apps.agents.exceptions import LLMServiceError
from apps.agents.models import BiasReport
from apps.email_engine.services.email_generator import EmailGenerator
from apps.email_engine.services.persistence import EmailPersistenceService
from apps.loans.models import LoanApplication

from .bias_detector import BiasDetector
from .step_tracker import StepTracker

logger = logging.getLogger("agents.orchestrator")


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

        # Inject counterfactual statements into profile_context for denial emails.
        # These are deterministic strings already produced by the orchestrator's
        # counterfactual_generation step — no new Claude API call.
        # IMPORTANT: the reverse OneToOne relation may be cached on `application`
        # from earlier in the orchestrator flow. Refresh from DB so we pick up
        # the counterfactual_results saved by the CF step.
        if decision == "denied":
            from apps.loans.models import LoanDecision

            try:
                decision_obj = LoanDecision.objects.get(application=application)
            except LoanDecision.DoesNotExist:
                decision_obj = None
            if decision_obj is not None:
                cf_results = decision_obj.counterfactual_results or []
                cf_statements = [cf["statement"] for cf in cf_results if isinstance(cf, dict) and cf.get("statement")]
                if cf_statements:
                    profile_context = {**(profile_context or {}), "counterfactual_statements": cf_statements}

        # Step 2: Generate Email
        step = self.tracker.start_step("email_generation")
        try:
            generator = EmailGenerator()
            email_result = generator.generate(
                application,
                decision,
                confidence=prediction_result["probability"],
                profile_context=profile_context,
            )

            generated_email = EmailPersistenceService.save_generated_email(application, decision, email_result)
            EmailPersistenceService.save_guardrail_logs(generated_email, email_result.get("guardrail_results", []))

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
            context = {
                "loan_amount": float(application.loan_amount),
                "purpose": application.get_purpose_display(),
                "decision": decision,
            }
            bias_result = bias_detector.analyze(email_result["body"], context)

            BiasReport.objects.create(
                agent_run=agent_run,
                email=generated_email,
                bias_score=bias_result["score"],
                deterministic_score=bias_result.get("deterministic_score"),
                llm_raw_score=bias_result.get("llm_raw_score"),
                score_source=bias_result.get("score_source", "composite"),
                categories=bias_result["categories"],
                analysis=bias_result["analysis"],
                flagged=bias_result["flagged"],
                requires_human_review=bias_result["requires_human_review"],
            )

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
            bias_result = {
                "score": 25,
                "flagged": False,
                "requires_human_review": False,
                "categories": [],
                "analysis": f"Bias check infrastructure error: {e}",
            }
        except Exception as e:
            logger.critical("Application %s: UNEXPECTED failure at bias_check: %s", application_id, e, exc_info=True)
            step = self.tracker.fail_step(step, str(e), failure_category=None)
            bias_result = {
                "score": 25,
                "flagged": False,
                "requires_human_review": False,
                "categories": [],
                "analysis": f"Bias check infrastructure error: {e}",
            }

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

        # Bias score above review threshold — escalate to human review
        if bias_score > bias_threshold_review:
            waterfall.append(
                StepTracker.waterfall_entry(
                    "final_decision",
                    "fail",
                    "ESCALATED_SEVERE_BIAS",
                    f"Severe bias detected (score {bias_score} > {bias_threshold_review}), escalated to human review",
                )
            )
            StepTracker.save_waterfall(application, waterfall)

            step = self.tracker.start_step("human_escalation_severe_bias")
            step = self.tracker.complete_step(
                step,
                result_summary={
                    "bias_score": bias_score,
                    "reason": f"Severe bias detected (score > {bias_threshold_review}), escalated directly to human reviewer",
                },
            )
            steps.append(step)
            logger.warning("Application %s: severe bias (score=%s), escalating", application_id, bias_score)

            step = self.tracker.start_step("human_review_required")
            step = self.tracker.complete_step(
                step,
                result_summary={
                    "review_category": "bias_escalation",
                    "reason": f"Severe bias detected (score {bias_score})",
                },
            )
            steps.append(step)

            with transaction.atomic():
                application.refresh_from_db()
                application.transition_to(
                    LoanApplication.Status.REVIEW,
                    details={"source": "email_pipeline_bias_escalation", "bias_score": bias_score},
                )
            agent_run.status = "escalated"
            return steps, email_result, generated_email, bias_result, True

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
            # Send decision email to customer (only when guardrails passed)
            step = self.tracker.start_step("email_delivery")
            try:
                from apps.email_engine.services.sender import send_decision_email

                recipient = application.applicant.email
                if recipient and generated_email:
                    send_result = send_decision_email(recipient, email_result["subject"], email_result["body"])
                    if send_result["sent"]:
                        step = self.tracker.complete_step(
                            step,
                            result_summary={
                                "sent": True,
                                "recipient": recipient,
                            },
                        )
                    else:
                        step = self.tracker.fail_step(step, send_result.get("error", "Send failed"))
                else:
                    step = self.tracker.complete_step(
                        step,
                        result_summary={
                            "sent": False,
                            "reason": "No recipient email or generated email missing",
                        },
                    )
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
