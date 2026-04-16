import logging
import time

from django.db import transaction

from apps.agents.exceptions import (
    MLPredictionError,
)
from apps.agents.models import AgentRun
from apps.loans.models import FraudCheck, LoanApplication, LoanDecision
from apps.loans.services.fraud_detection import FraudDetectionService
from apps.ml_engine.models import PredictionLog
from apps.ml_engine.services.counterfactual_engine import CounterfactualEngine
from apps.ml_engine.services.predictor import ModelPredictor

from .bias_detector import AIEmailReviewer, BiasDetector, MarketingBiasDetector, MarketingEmailReviewer  # noqa: F401
from .context_builder import ApplicationContextBuilder
from .email_pipeline import EmailPipelineService
from .human_review_handler import HumanReviewHandler
from .marketing_pipeline import MarketingPipelineService
from .step_tracker import STEP_TIMEOUT_BUDGETS_MS, StepTracker  # noqa: F401 — re-exported

logger = logging.getLogger("agents.orchestrator")


class PipelineOrchestrator:
    """Runs the full loan processing pipeline end to end."""

    def __init__(self):
        self._step_tracker = StepTracker()
        self._context_builder = ApplicationContextBuilder()
        self._email_pipeline = EmailPipelineService(self._step_tracker)
        self._marketing_pipeline = MarketingPipelineService(self._step_tracker)
        self._human_review_handler = HumanReviewHandler(self._step_tracker, self._context_builder)

    # ------------------------------------------------------------------
    # Delegate step-tracking methods so existing callers (including tests
    # that instantiate PipelineOrchestrator directly) keep working.
    # ------------------------------------------------------------------

    @staticmethod
    def _waterfall_entry(step: str, result: str, reason_code: str, detail: str) -> dict:
        return StepTracker.waterfall_entry(step, result, reason_code, detail)

    @staticmethod
    def _save_waterfall(application, waterfall: list) -> None:
        StepTracker.save_waterfall(application, waterfall)

    def _build_profile_context(self, application):
        return self._context_builder.build_profile_context(application)

    @staticmethod
    def _evaluate_conditions(application) -> list:
        return ApplicationContextBuilder.evaluate_conditions(application)

    def _start_step(self, step_name):
        return self._step_tracker.start_step(step_name)

    def _complete_step(self, step, result_summary=None):
        return self._step_tracker.complete_step(step, result_summary)

    def _fail_step(self, step, error, failure_category=None):
        return self._step_tracker.fail_step(step, error, failure_category)

    def _categorize_error(self, error):
        return self._step_tracker.categorize_error(error)

    def _finalize_run(self, agent_run, steps, start_time, error=None):
        return self._step_tracker.finalize_run(agent_run, steps, start_time, error)

    def _run_nbo_and_marketing_pipeline(self, application, agent_run, steps, denial_reasons, profile_context):
        return self._marketing_pipeline.run(application, agent_run, steps, denial_reasons, profile_context)

    def _run_marketing_bias_check(self, email_result_marketing, application, agent_run, steps):
        return self._marketing_pipeline.check_bias(email_result_marketing, application, agent_run, steps)

    # ------------------------------------------------------------------
    # Counterfactual generation (denied applications only)
    # ------------------------------------------------------------------

    def _run_counterfactual_step(self, prediction_result, predictor, original_loan_amount):
        """Generate DiCE counterfactual explanations for denied applications.

        Returns a list of counterfactual dicts, or [] if prediction is not
        denied or if generation fails.
        """
        if prediction_result.get("prediction") != "denied":
            return []

        try:
            features_df = prediction_result.get("_features_df")
            if features_df is None:
                logger.warning("Counterfactual step: no _features_df in prediction result")
                return []

            engine = CounterfactualEngine(
                model=predictor.model,
                feature_cols=predictor.feature_cols,
                training_data=features_df,
                threshold=predictor.model_version.optimal_threshold or 0.5,
                # Pass the predictor's transform so candidate raw-feature
                # values are scored through the same engineered + one-hot
                # pipeline the live model expects.
                transform_fn=predictor._transform,
            )
            return engine.generate(features_df, original_loan_amount, timeout_seconds=10)
        except Exception as e:
            logger.warning("Counterfactual generation failed in orchestrator: %s", e)
            return []

    # ------------------------------------------------------------------
    # Main orchestration
    # ------------------------------------------------------------------

    def orchestrate(self, application_id):
        start_time = time.time()
        logger.info("Starting pipeline for application %s", application_id)

        with transaction.atomic():
            application = LoanApplication.objects.select_for_update().select_related("applicant").get(pk=application_id)
            if application.status == "processing":
                # If processing for more than 10 minutes, treat as stale/stuck.
                # Must exceed Celery soft_time_limit (540s / 9min) to avoid
                # race conditions where a slow-but-alive task is treated as stale.
                from django.utils import timezone as tz

                stale_threshold = tz.now() - tz.timedelta(minutes=10)
                if application.updated_at > stale_threshold:
                    raise ValueError("Pipeline already running for this application")
                logger.warning(
                    "Application %s: stale processing status (updated_at=%s), resetting",
                    application_id,
                    application.updated_at,
                )
                # Mark any zombie agent runs as failed
                AgentRun.objects.filter(
                    application=application,
                    status__in=(AgentRun.Status.PENDING, AgentRun.Status.RUNNING),
                ).update(status=AgentRun.Status.FAILED, error="Stale pipeline — automatically cleared")
                application.transition_to("pending", details={"source": "stale_pipeline_reset"})
            application.transition_to("processing", details={"source": "orchestrator_pipeline"})

        # Refetch with profile (nullable) outside the lock — select_for_update
        # cannot be combined with outer joins on nullable relations in PostgreSQL.
        application = LoanApplication.objects.select_related("applicant__profile").get(pk=application_id)
        profile_context = self._build_profile_context(application)

        agent_run = AgentRun.objects.create(
            application=application,
            status=AgentRun.Status.RUNNING,
            steps=[],
        )

        steps = []
        waterfall = []
        prediction_result = None

        # Step 0: Fraud Detection / Velocity Checks
        step = self._start_step("fraud_check")
        try:
            fraud_service = FraudDetectionService()
            fraud_result = fraud_service.run_checks(application)

            FraudCheck.objects.create(
                application=application,
                passed=fraud_result["passed"],
                risk_score=fraud_result["risk_score"],
                checks=fraud_result["checks"],
                flagged_reasons=fraud_result["flagged_reasons"],
            )

            fraud_status = "pass" if fraud_result["passed"] else "fail"
            fraud_reason = "FRAUD_CLEAR" if fraud_result["passed"] else "FRAUD_VELOCITY"
            fraud_detail = (
                "No fraud indicators detected"
                if fraud_result["passed"]
                else f"Fraud flags: {'; '.join(fraud_result['flagged_reasons'])}"
            )
            waterfall.append(
                self._waterfall_entry(
                    "fraud_check",
                    fraud_status,
                    fraud_reason,
                    fraud_detail,
                )
            )

            step = self._complete_step(
                step,
                result_summary={
                    "passed": fraud_result["passed"],
                    "risk_score": fraud_result["risk_score"],
                    "flagged_reasons": fraud_result["flagged_reasons"],
                },
            )
            logger.info(
                "Application %s: fraud check passed=%s risk_score=%.2f",
                application_id,
                fraud_result["passed"],
                fraud_result["risk_score"],
            )
        except Exception as e:
            logger.critical("Application %s: UNEXPECTED failure at fraud_check: %s", application_id, e, exc_info=True)
            waterfall.append(
                self._waterfall_entry(
                    "fraud_check",
                    "skip",
                    "FRAUD_CHECK_ERROR",
                    f"Fraud check infrastructure failure: {e}",
                )
            )
            step = self._fail_step(step, str(e), failure_category=None)
            # Fraud check infra failure — continue to ML prediction rather than blocking
            fraud_result = {"passed": True, "risk_score": 0.0, "checks": [], "flagged_reasons": []}

        steps.append(step)

        # Fraud check is informational only — logged in waterfall but does not
        # block the pipeline or escalate to human review.
        if not fraud_result["passed"]:
            logger.warning(
                "Application %s: fraud flags noted — %s", application_id, "; ".join(fraud_result["flagged_reasons"])
            )

        # Step 1: ML Prediction
        step = self._start_step("ml_prediction")
        try:
            predictor = ModelPredictor()
            prediction_result = predictor.predict(application)

            PredictionLog.objects.create(
                model_version_id=prediction_result["model_version"],
                application=application,
                prediction=prediction_result["prediction"],
                probability=prediction_result["probability"],
                feature_importances=prediction_result["feature_importances"],
                processing_time_ms=prediction_result["processing_time_ms"],
            )

            from apps.loans.models import AuditLog

            AuditLog.objects.create(
                action="prediction_completed",
                resource_type="LoanApplication",
                resource_id=str(application.pk),
                details={
                    "prediction": prediction_result["prediction"],
                    "probability": round(prediction_result["probability"], 4),
                    "requires_human_review": prediction_result.get("requires_human_review", False),
                },
            )

            LoanDecision.objects.update_or_create(
                application=application,
                defaults={
                    "decision": prediction_result["prediction"],
                    "confidence": prediction_result["probability"],
                    "feature_importances": prediction_result["feature_importances"],
                    "shap_values": prediction_result.get("shap_values", {}),
                    "decision_waterfall": [],
                    "model_version_id": prediction_result["model_version"],
                },
            )

            # Record policy-level waterfall entries derived from application data
            if application.has_bankruptcy:
                waterfall.append(
                    self._waterfall_entry(
                        "policy_rules",
                        "fail",
                        "BANKRUPTCY_FLAG",
                        "Applicant has undischarged bankruptcy or within 7-year window",
                    )
                )
            else:
                waterfall.append(
                    self._waterfall_entry(
                        "policy_rules",
                        "pass",
                        "BANKRUPTCY_CLEAR",
                        "No bankruptcy flag on application",
                    )
                )

            dti = float(application.debt_to_income)
            dti_cap = 6.0
            if dti > dti_cap:
                waterfall.append(
                    self._waterfall_entry(
                        "policy_rules",
                        "fail",
                        "DTI_EXCEEDED",
                        f"Debt-to-income ratio {dti:.2f} exceeds cap of {dti_cap}",
                    )
                )
            else:
                waterfall.append(
                    self._waterfall_entry(
                        "policy_rules",
                        "pass",
                        "DTI_WITHIN_LIMIT",
                        f"Debt-to-income ratio {dti:.2f} within cap of {dti_cap}",
                    )
                )

            # ML prediction waterfall entry
            prob = prediction_result["probability"]
            ml_result = "pass" if prediction_result["prediction"] == "approved" else "fail"
            ml_reason = "MODEL_APPROVED" if ml_result == "pass" else "MODEL_DENIED"
            waterfall.append(
                self._waterfall_entry(
                    "ml_prediction",
                    ml_result,
                    ml_reason,
                    f"Model prediction: {prediction_result['prediction']} "
                    f"(confidence={prob:.4f}, model={prediction_result['model_version']})",
                )
            )

            step = self._complete_step(
                step,
                result_summary={
                    "prediction": prediction_result["prediction"],
                    "probability": prediction_result["probability"],
                },
            )
            logger.info(
                "Application %s: prediction=%s prob=%.3f",
                application_id,
                prediction_result["prediction"],
                prediction_result["probability"],
            )
        except (MLPredictionError, ConnectionError, TimeoutError) as e:
            logger.error("Application %s: ML prediction failed: %s", application_id, e)
            waterfall.append(
                self._waterfall_entry(
                    "ml_prediction",
                    "fail",
                    "MODEL_ERROR",
                    f"ML prediction failed: {e}",
                )
            )
            self._save_waterfall(application, waterfall)
            step = self._fail_step(step, str(e), failure_category="transient")
            self._finalize_run(agent_run, steps + [step], start_time, error=str(e))
            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(status=LoanApplication.Status.REVIEW)
            return agent_run
        except Exception as e:
            logger.critical("Application %s: UNEXPECTED failure at ml_prediction: %s", application_id, e, exc_info=True)
            waterfall.append(
                self._waterfall_entry(
                    "ml_prediction",
                    "fail",
                    "MODEL_ERROR",
                    f"ML prediction unexpected failure: {e}",
                )
            )
            self._save_waterfall(application, waterfall)
            step = self._fail_step(step, str(e), failure_category=None)
            self._finalize_run(agent_run, steps + [step], start_time, error=str(e))
            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(status=LoanApplication.Status.REVIEW)
            return agent_run

        steps.append(step)
        decision = prediction_result["prediction"]  # 'approved' or 'denied'

        # Step 1b: Counterfactual generation (denied applications only)
        if decision == "denied":
            step = self._start_step("counterfactual_generation")
            try:
                cf_results = self._run_counterfactual_step(
                    prediction_result,
                    predictor,
                    float(application.loan_amount),
                )
                # Persist counterfactuals on the LoanDecision
                loan_decision = LoanDecision.objects.filter(application=application).first()
                if loan_decision and cf_results:
                    loan_decision.counterfactual_results = cf_results
                    loan_decision.save(update_fields=["counterfactual_results"])

                step = self._complete_step(
                    step,
                    result_summary={"count": len(cf_results)},
                )
                logger.info(
                    "Application %s: generated %d counterfactual(s)",
                    application_id,
                    len(cf_results),
                )
            except Exception as e:
                logger.warning(
                    "Application %s: counterfactual generation failed: %s",
                    application_id,
                    e,
                )
                step = self._fail_step(step, str(e))
            steps.append(step)

        # Steps 2-4: Email generation, bias check, delivery (delegated)
        steps, email_result, generated_email, bias_result, escalated = self._email_pipeline.run(
            application,
            agent_run,
            profile_context,
            prediction_result,
            decision,
            steps,
            waterfall,
        )

        if escalated:
            self._finalize_run(agent_run, steps, start_time)
            return agent_run

        # Email pipeline failure — finalize and return
        if email_result is None and generated_email is None and bias_result is None:
            # Email generation failed — find the error from the last step
            last_step = steps[-1] if steps else {}
            error_msg = last_step.get("error", "Email generation failed")
            self._finalize_run(agent_run, steps, start_time, error=error_msg)
            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(status=decision)
            return agent_run

        # Step 5: NBO + Marketing pipeline (if denied)
        if decision == "denied":
            denial_reasons = ""
            shap_vals = prediction_result.get("shap_values") if prediction_result else None
            if shap_vals:
                # Use per-applicant SHAP values — negative values are denial drivers
                negative = {k: abs(v) for k, v in shap_vals.items() if v < 0}
                if negative:
                    top_factors = sorted(negative.items(), key=lambda x: x[1], reverse=True)[:3]
                    denial_reasons = ", ".join(f"{k}: {v:.3f}" for k, v in top_factors)
            if not denial_reasons and prediction_result and prediction_result.get("feature_importances"):
                top_factors = sorted(
                    prediction_result["feature_importances"].items(), key=lambda x: x[1], reverse=True
                )[:3]
                denial_reasons = ", ".join(f"{k}: {v:.3f}" for k, v in top_factors)

            steps = self._run_nbo_and_marketing_pipeline(
                application,
                agent_run,
                steps,
                denial_reasons,
                profile_context,
            )

        # Final decision waterfall entry
        final_reason = "APPROVED" if decision == "approved" else "DENIED"
        waterfall.append(
            self._waterfall_entry(
                "final_decision",
                "pass" if decision == "approved" else "fail",
                final_reason,
                f"Pipeline completed with decision: {decision}",
            )
        )

        # No bias escalation — apply ML decision directly.
        # Human review is exclusively for bias-flagged applications.
        self._save_waterfall(application, waterfall)

        with transaction.atomic():
            LoanApplication.objects.filter(pk=application.pk).update(status=decision)
        agent_run.status = "completed"
        self._finalize_run(agent_run, steps, start_time)
        logger.info(
            "Application %s: pipeline completed — decision=%s",
            application_id,
            decision,
        )

        return agent_run

    def resume_after_review(self, agent_run_id, reviewer="", note=""):
        return self._human_review_handler.resume_after_review(agent_run_id, reviewer, note)
