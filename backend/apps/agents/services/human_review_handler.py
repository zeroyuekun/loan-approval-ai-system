import logging
import time

from django.db import transaction

from apps.agents.exceptions import LLMServiceError
from apps.agents.models import AgentRun
from apps.email_engine.services.email_generator import EmailGenerator
from apps.email_engine.services.persistence import EmailPersistenceService
from apps.loans.models import LoanApplication, LoanDecision

from .context_builder import ApplicationContextBuilder
from .marketing_pipeline import MarketingPipelineService
from .step_tracker import StepTracker

logger = logging.getLogger("agents.orchestrator")


class HumanReviewHandler:
    """Handles resuming the pipeline after human review."""

    def __init__(self, step_tracker: StepTracker, context_builder: ApplicationContextBuilder):
        self.tracker = step_tracker
        self.context_builder = context_builder

    def resume_after_review(self, agent_run_id, reviewer="", note=""):
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

            if agent_run.status != "escalated":
                raise ValueError(f'Cannot resume agent run with status {agent_run.status!r} (expected "escalated")')

            application = agent_run.application

            # Lock application to prevent two simultaneous reviews from resuming
            LoanApplication.objects.select_for_update().get(pk=application.pk)
            if application.status != "review":
                raise ValueError(f'Cannot resume: application status is {application.status!r} (expected "review")')

            try:
                _ = application.decision
            except LoanDecision.DoesNotExist as err:
                raise ValueError(f"No decision found for application {application.id}") from err

            decision = application.decision.decision

            # Mark as running inside the lock to prevent duplicate resume
            agent_run.status = "running"
            agent_run.save(update_fields=["status"])

        # Refetch with profile outside the lock (nullable relation can't be in select_for_update)
        application = LoanApplication.objects.select_related("applicant__profile", "decision").get(pk=application.pk)
        profile_context = self.context_builder.build_profile_context(application)
        steps = agent_run.steps or []

        # Record the human approval
        step = self.tracker.start_step("human_review_approved")
        step = self.tracker.complete_step(
            step,
            result_summary={
                "reviewer": reviewer,
                "note": note,
                "action": "approve",
            },
        )
        steps.append(step)

        if decision == "approved":
            # Human approved an escalated application — re-generate and send approval email
            step = self.tracker.start_step("email_generation")
            try:
                generator = EmailGenerator()
                email_result = generator.generate(
                    application,
                    "approved",
                    confidence=application.decision.confidence,
                    profile_context=profile_context,
                )

                generated_email = EmailPersistenceService.save_generated_email(application, "approved", email_result)
                EmailPersistenceService.save_guardrail_logs(generated_email, email_result.get("guardrail_results", []))

                step = self.tracker.complete_step(
                    step,
                    result_summary={
                        "subject": email_result["subject"],
                        "passed_guardrails": email_result["passed_guardrails"],
                    },
                )
            except (LLMServiceError, ConnectionError, TimeoutError) as e:
                logger.error("Agent run %s: approval email generation failed: %s", agent_run_id, e)
                step = self.tracker.fail_step(step, str(e), failure_category="transient")
                email_result = None
            except Exception as e:
                logger.critical(
                    "Agent run %s: UNEXPECTED failure at approval email_generation: %s",
                    agent_run_id,
                    e,
                    exc_info=True,
                )
                step = self.tracker.fail_step(step, str(e), failure_category=None)
                email_result = None
            steps.append(step)

            # Guardrail failure on resume -> re-escalate for human review
            if email_result and not email_result.get("passed_guardrails"):
                failed_checks = [r["check_name"] for r in email_result.get("guardrail_results", []) if not r["passed"]]
                logger.warning(
                    "Agent run %s: approval email guardrails failed on resume — re-escalating. Failed checks: %s",
                    agent_run_id,
                    ", ".join(failed_checks),
                )
                step = self.tracker.start_step("email_delivery")
                step = self.tracker.complete_step(
                    step,
                    result_summary={
                        "sent": False,
                        "reason": "Guardrails failed on resume — re-escalated to human review",
                        "failed_guardrails": failed_checks,
                    },
                )
                steps.append(step)
                agent_run.status = "escalated"
                agent_run.error = f"Email guardrails failed on resume: {', '.join(failed_checks)}"
                self.tracker.finalize_run(agent_run, steps, start_time)
                return agent_run

            # Send the approval email
            if email_result:
                step = self.tracker.start_step("email_delivery")
                try:
                    from apps.email_engine.services.sender import send_decision_email

                    recipient = application.applicant.email
                    if recipient:
                        send_result = send_decision_email(
                            recipient,
                            email_result["subject"],
                            email_result["body"],
                            email_type="approval" if decision == "approved" else "denial",
                        )
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
                                "reason": "No recipient email",
                            },
                        )
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.error("Agent run %s: approval email delivery failed: %s", agent_run_id, e)
                    step = self.tracker.fail_step(step, str(e), failure_category="transient")
                except Exception as e:
                    logger.critical(
                        "Agent run %s: UNEXPECTED failure at approval email_delivery: %s",
                        agent_run_id,
                        e,
                        exc_info=True,
                    )
                    step = self.tracker.fail_step(step, str(e), failure_category=None)
                steps.append(step)

        elif decision == "denied":
            # Extract denial reasons from stored feature importances
            denial_reasons = ""
            try:
                fi = application.decision.feature_importances
                if fi:
                    top_factors = sorted(fi.items(), key=lambda x: x[1], reverse=True)[:3]
                    denial_reasons = ", ".join(f"{k}: {v:.3f}" for k, v in top_factors)
            except (LoanDecision.DoesNotExist, AttributeError) as exc:
                logger.debug(
                    "denial_feature_importances_missing",
                    extra={
                        "agent_run_id": str(agent_run_id),
                        "application_id": str(application.id),
                        "error": type(exc).__name__,
                    },
                )

            marketing_pipeline = MarketingPipelineService(self.tracker)
            steps = marketing_pipeline.run(
                application,
                agent_run,
                steps,
                denial_reasons,
                profile_context,
            )

        # Finalize — finalize_run sets status to 'completed' internally
        with transaction.atomic():
            application.refresh_from_db()
            application.transition_to(
                decision,
                details={"source": "human_review_resume", "officer": reviewer or "", "note": note or ""},
            )
        self.tracker.finalize_run(agent_run, steps, start_time)
        logger.info("Agent run %s: resumed and completed with decision=%s", agent_run_id, decision)

        return agent_run
