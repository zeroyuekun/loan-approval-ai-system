import logging

from django.conf import settings

from apps.agents.exceptions import LLMServiceError
from apps.agents.models import BiasReport, MarketingEmail, NextBestOffer

from .bias_detector import MarketingBiasDetector, MarketingEmailReviewer
from .marketing_agent import MarketingAgent
from .next_best_offer import NextBestOfferGenerator
from .step_tracker import StepTracker

logger = logging.getLogger("agents.orchestrator")


class MarketingPipelineService:
    """NBO + marketing email pipeline for denied applications."""

    def __init__(self, step_tracker: StepTracker):
        self.tracker = step_tracker

    def run(self, application, agent_run, steps, denial_reasons, profile_context):
        """Run the full NBO + marketing email pipeline. Returns updated steps list."""
        nbo_result = None
        nbo_generator = NextBestOfferGenerator()

        # NBO generation
        step = self.tracker.start_step("next_best_offers")
        try:
            nbo_result = nbo_generator.generate(application, denial_reasons=denial_reasons)

            nbo_record = NextBestOffer.objects.create(
                agent_run=agent_run,
                application=application,
                offers=nbo_result["offers"],
                analysis=nbo_result["analysis"],
                customer_retention_score=nbo_result.get("customer_retention_score", 0),
                loyalty_factors=nbo_result.get("loyalty_factors", []),
                personalized_message=nbo_result.get("personalized_message", ""),
            )

            step = self.tracker.complete_step(
                step,
                result_summary={
                    "num_offers": len(nbo_result["offers"]),
                    "customer_retention_score": nbo_result.get("customer_retention_score", 0),
                },
            )
        except (LLMServiceError, ConnectionError, TimeoutError) as e:
            logger.error("Application %s: NBO generation failed: %s", application.pk, e)
            step = self.tracker.fail_step(step, str(e), failure_category="transient")
        except Exception as e:
            logger.critical(
                "Application %s: UNEXPECTED failure at next_best_offers: %s", application.pk, e, exc_info=True
            )
            step = self.tracker.fail_step(step, str(e), failure_category=None)

        steps.append(step)

        if not nbo_result or not nbo_result.get("offers"):
            logger.warning(
                "Application %s: no NBO offers generated — skipping marketing email pipeline", application.pk
            )

        # Marketing Message Generation (if NBO succeeded)
        if nbo_result and nbo_result.get("offers"):
            step = self.tracker.start_step("marketing_message_generation")
            try:
                marketing_result = nbo_generator.generate_marketing_message(
                    application,
                    nbo_result["offers"],
                    denial_reasons=denial_reasons,
                )
                nbo_record.marketing_message = marketing_result["marketing_message"]
                nbo_record.save(update_fields=["marketing_message"])

                step = self.tracker.complete_step(
                    step,
                    result_summary={
                        "message_length": len(marketing_result["marketing_message"]),
                        "generation_time_ms": marketing_result["generation_time_ms"],
                    },
                )
            except (LLMServiceError, ConnectionError, TimeoutError) as e:
                logger.error("Application %s: marketing message failed: %s", application.pk, e)
                step = self.tracker.fail_step(step, str(e), failure_category="transient")
            except Exception as e:
                logger.critical(
                    "Application %s: UNEXPECTED failure at marketing_message_generation: %s",
                    application.pk,
                    e,
                    exc_info=True,
                )
                step = self.tracker.fail_step(step, str(e), failure_category=None)

            steps.append(step)

        # Marketing Agent Email (if NBO succeeded)
        if nbo_result and nbo_result.get("offers"):
            step = self.tracker.start_step("marketing_email_generation")
            email_result_marketing = None
            try:
                marketing_agent = MarketingAgent()
                email_result_marketing = marketing_agent.generate(
                    application,
                    nbo_result,
                    denial_reasons=denial_reasons,
                )

                step = self.tracker.complete_step(
                    step,
                    result_summary={
                        "subject": email_result_marketing["subject"],
                        "passed_guardrails": email_result_marketing["passed_guardrails"],
                        "attempt_number": email_result_marketing["attempt_number"],
                        "generation_time_ms": email_result_marketing["generation_time_ms"],
                    },
                )
            except (LLMServiceError, ConnectionError, TimeoutError) as e:
                logger.error("Application %s: marketing email generation failed: %s", application.pk, e)
                step = self.tracker.fail_step(step, str(e), failure_category="transient")
            except Exception as e:
                logger.critical(
                    "Application %s: UNEXPECTED failure at marketing_email_generation: %s",
                    application.pk,
                    e,
                    exc_info=True,
                )
                step = self.tracker.fail_step(step, str(e), failure_category=None)

            steps.append(step)

            # Marketing bias check -> save -> send
            # Always save the marketing email to DB regardless of bias outcome
            if email_result_marketing:
                send_approved = False
                if email_result_marketing.get("passed_guardrails"):
                    try:
                        steps, send_approved = self.check_bias(
                            email_result_marketing,
                            application,
                            agent_run,
                            steps,
                        )
                    except (LLMServiceError, ConnectionError, TimeoutError) as e:
                        logger.error("Application %s: marketing bias check failed: %s", application.pk, e)
                        send_approved = False
                    except Exception as e:
                        logger.critical(
                            "Application %s: UNEXPECTED failure at marketing_bias_check: %s",
                            application.pk,
                            e,
                            exc_info=True,
                        )
                        send_approved = False

                logger.info("Application %s: marketing send_approved=%s", application.pk, send_approved)

                # Single save point for MarketingEmail
                marketing_email_obj = MarketingEmail.objects.create(
                    agent_run=agent_run,
                    application=application,
                    subject=email_result_marketing["subject"],
                    body=email_result_marketing["body"],
                    prompt_used=email_result_marketing["prompt_used"],
                    generation_time_ms=email_result_marketing["generation_time_ms"],
                    attempt_number=email_result_marketing["attempt_number"],
                    passed_guardrails=email_result_marketing["passed_guardrails"],
                    guardrail_results=email_result_marketing["guardrail_results"],
                )

                # Link the marketing BiasReport to the MarketingEmail record
                BiasReport.objects.filter(
                    agent_run=agent_run,
                    report_type="marketing",
                    marketing_email__isnull=True,
                ).update(marketing_email=marketing_email_obj)

                # Send if approved, otherwise record why it was blocked
                if send_approved:
                    step = self.tracker.start_step("marketing_email_delivery")
                    try:
                        from apps.email_engine.services.sender import send_decision_email

                        recipient = application.applicant.email
                        if recipient:
                            send_result = send_decision_email(
                                recipient,
                                email_result_marketing["subject"],
                                email_result_marketing["body"],
                                email_type="marketing",
                            )
                            if send_result["sent"]:
                                from django.utils import timezone as tz

                                marketing_email_obj.sent = True
                                marketing_email_obj.sent_at = tz.now()
                                marketing_email_obj.save(update_fields=["sent", "sent_at"])
                                step = self.tracker.complete_step(
                                    step,
                                    result_summary={
                                        "sent": True,
                                        "recipient": recipient,
                                    },
                                )
                            else:
                                marketing_email_obj.delivery_error = send_result.get("error", "Send failed")
                                marketing_email_obj.save(update_fields=["delivery_error"])
                                step = self.tracker.fail_step(step, send_result.get("error", "Send failed"))
                        else:
                            marketing_email_obj.blocked_reason = "no_recipient_email"
                            marketing_email_obj.save(update_fields=["blocked_reason"])
                            step = self.tracker.complete_step(
                                step,
                                result_summary={
                                    "sent": False,
                                    "reason": "No recipient email",
                                },
                            )
                    except (ConnectionError, TimeoutError, OSError) as e:
                        logger.error("Application %s: marketing email delivery failed: %s", application.pk, e)
                        marketing_email_obj.delivery_error = str(e)
                        marketing_email_obj.save(update_fields=["delivery_error"])
                        step = self.tracker.fail_step(step, str(e), failure_category="transient")
                    except Exception as e:
                        logger.critical(
                            "Application %s: UNEXPECTED failure at marketing_email_delivery: %s",
                            application.pk,
                            e,
                            exc_info=True,
                        )
                        marketing_email_obj.delivery_error = str(e)
                        marketing_email_obj.save(update_fields=["delivery_error"])
                        step = self.tracker.fail_step(step, str(e), failure_category=None)

                    steps.append(step)
                else:
                    # Record why it was blocked
                    reason = (
                        "bias_check_failed" if email_result_marketing.get("passed_guardrails") else "guardrails_failed"
                    )
                    marketing_email_obj.blocked_reason = reason
                    marketing_email_obj.save(update_fields=["blocked_reason"])

        return steps

    def check_bias(self, email_result_marketing, application, agent_run, steps):
        """Run marketing bias check and AI review if needed. Returns (steps, send_approved)."""
        marketing_context = {
            "loan_amount": float(application.loan_amount),
            "purpose": application.get_purpose_display(),
            "decision": "denied",
        }

        bias_threshold_pass = getattr(settings, "MARKETING_BIAS_THRESHOLD_PASS", 50)
        bias_threshold_review = getattr(settings, "MARKETING_BIAS_THRESHOLD_REVIEW", 70)

        step = self.tracker.start_step("marketing_bias_check")
        marketing_bias_result = {"score": 100, "flagged": True, "requires_human_review": True}
        try:
            detector = MarketingBiasDetector()
            marketing_bias_result = detector.analyze(
                email_result_marketing["body"],
                marketing_context,
            )

            # Create a BiasReport record for the marketing email bias check
            BiasReport.objects.create(
                agent_run=agent_run,
                report_type="marketing",
                bias_score=marketing_bias_result["score"],
                deterministic_score=marketing_bias_result.get("deterministic_score"),
                llm_raw_score=marketing_bias_result.get("llm_raw_score"),
                score_source=marketing_bias_result.get("score_source", "composite"),
                categories=marketing_bias_result["categories"],
                analysis=marketing_bias_result["analysis"],
                flagged=marketing_bias_result["flagged"],
                requires_human_review=marketing_bias_result["requires_human_review"],
            )

            step = self.tracker.complete_step(
                step,
                result_summary={
                    "bias_score": marketing_bias_result["score"],
                    "flagged": marketing_bias_result["flagged"],
                },
            )
        except (LLMServiceError, ConnectionError, TimeoutError) as e:
            logger.error("Application %s: marketing bias check failed: %s", application.pk, e)
            step = self.tracker.fail_step(step, str(e), failure_category="transient")
            marketing_bias_result = {"score": 100, "flagged": True, "requires_human_review": True}
        except Exception as e:
            logger.critical(
                "Application %s: UNEXPECTED failure at marketing_bias_check: %s", application.pk, e, exc_info=True
            )
            step = self.tracker.fail_step(step, str(e), failure_category=None)
            marketing_bias_result = {"score": 100, "flagged": True, "requires_human_review": True}
        steps.append(step)

        marketing_bias_score = marketing_bias_result.get("score", 100)

        # Inclusive bound: a score equal to the review threshold must block.
        if marketing_bias_score >= bias_threshold_review:
            logger.warning(
                "Application %s: marketing email blocked — bias score %s >= review threshold %s",
                application.pk,
                marketing_bias_score,
                bias_threshold_review,
            )
            step = self.tracker.start_step("marketing_email_blocked")
            step = self.tracker.complete_step(
                step,
                result_summary={
                    "bias_score": marketing_bias_score,
                    "reason": f"Marketing email blocked: bias score {marketing_bias_score} >= threshold {bias_threshold_review}",
                },
            )
            steps.append(step)
            return steps, False

        if bias_threshold_pass < marketing_bias_score <= bias_threshold_review:
            step = self.tracker.start_step("marketing_ai_review")
            review_result = {"approved": False}
            try:
                reviewer = MarketingEmailReviewer()
                review_result = reviewer.review(
                    email_result_marketing["body"],
                    marketing_bias_result,
                    marketing_context,
                )
                step = self.tracker.complete_step(
                    step,
                    result_summary={
                        "approved": review_result["approved"],
                        "confidence": review_result["confidence"],
                    },
                )
            except (LLMServiceError, ConnectionError, TimeoutError) as e:
                logger.error("Application %s: marketing AI review failed: %s", application.pk, e)
                step = self.tracker.fail_step(step, str(e), failure_category="transient")
                review_result = {"approved": False}
            except Exception as e:
                logger.critical(
                    "Application %s: UNEXPECTED failure at marketing_ai_review: %s", application.pk, e, exc_info=True
                )
                step = self.tracker.fail_step(step, str(e), failure_category=None)
                review_result = {"approved": False}
            steps.append(step)

            if not review_result.get("approved", False):
                logger.warning("Application %s: marketing email blocked by senior reviewer", application.pk)
                step = self.tracker.start_step("marketing_email_blocked")
                step = self.tracker.complete_step(
                    step,
                    result_summary={
                        "bias_score": marketing_bias_score,
                        "reason": "Senior reviewer blocked marketing email after bias flag",
                    },
                )
                steps.append(step)
                return steps, False

        logger.info("Application %s: marketing email approved for sending", application.pk)
        return steps, True
