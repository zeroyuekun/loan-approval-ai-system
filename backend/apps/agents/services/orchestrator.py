import logging
import time
from datetime import datetime, timezone

from django.conf import settings
from django.db import transaction

from apps.agents.models import AgentRun, BiasReport, MarketingEmail, NextBestOffer
from apps.email_engine.services.email_generator import EmailGenerator
from apps.email_engine.services.persistence import EmailPersistenceService
from apps.loans.models import FraudCheck, LoanApplication, LoanDecision
from apps.loans.services.fraud_detection import FraudDetectionService
from apps.ml_engine.models import PredictionLog
from apps.ml_engine.services.predictor import ModelPredictor

from apps.agents.exceptions import (
    LLMServiceError, MLPredictionError, PipelineStepError,
)

from .bias_detector import AIEmailReviewer, BiasDetector, MarketingBiasDetector, MarketingEmailReviewer
from .marketing_agent import MarketingAgent
from .next_best_offer import NextBestOfferGenerator

logger = logging.getLogger('agents.orchestrator')

# Step timeout budgets — configurable via settings for environment-specific tuning.
STEP_TIMEOUT_BUDGETS_MS = getattr(settings, 'ORCHESTRATOR_STEP_TIMEOUTS', {
    'fraud_check': 10_000,
    'ml_prediction': 30_000,
    'email_generation': 60_000,
    'bias_check': 60_000,
    'ai_email_review': 60_000,
    'email_delivery': 30_000,
    'next_best_offers': 60_000,
    'marketing_message_generation': 60_000,
    'marketing_email_generation': 60_000,
    'marketing_bias_check': 60_000,
    'marketing_ai_review': 60_000,
    'marketing_email_delivery': 30_000,
    'human_escalation': 5_000,
    'human_escalation_severe_bias': 5_000,
    'human_escalation_low_confidence': 5_000,
    'human_review_approved': 5_000,
    'marketing_email_blocked': 5_000,
})


class PipelineOrchestrator:
    """Runs the full loan processing pipeline end to end."""

    @staticmethod
    def _waterfall_entry(step: str, result: str, reason_code: str, detail: str) -> dict:
        """Create a single decision waterfall entry for ASIC RG 209 audit trail."""
        return {
            'step': step,
            'result': result,
            'reason_code': reason_code,
            'detail': detail,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _save_waterfall(application, waterfall: list) -> None:
        """Persist the decision waterfall to the LoanDecision record."""
        LoanDecision.objects.filter(application=application).update(
            decision_waterfall=waterfall,
        )

    def _build_profile_context(self, application):
        """Build a dict of customer profile data for downstream services.

        Returns None if the profile is not available so callers can degrade
        gracefully.
        """
        try:
            profile = application.applicant.profile
        except (AttributeError,):  # RelatedObjectDoesNotExist is a subclass
            logger.info('Application %s: no customer profile available', application.pk)
            return None

        return {
            'savings_balance': getattr(profile, 'savings_balance', None),
            'checking_balance': getattr(profile, 'checking_balance', None),
            'account_tenure_years': getattr(profile, 'account_tenure_years', None),
            'loyalty_tier': profile.get_loyalty_tier_display() if hasattr(profile, 'get_loyalty_tier_display') else None,
            'num_products': getattr(profile, 'num_products', None),
            'on_time_payment_pct': getattr(profile, 'on_time_payment_pct', None),
            'previous_loans_repaid': getattr(profile, 'previous_loans_repaid', None),
            'has_credit_card': getattr(profile, 'has_credit_card', None),
            'has_mortgage': getattr(profile, 'has_mortgage', None),
            'has_auto_loan': getattr(profile, 'has_auto_loan', None),
            'gross_annual_income': getattr(profile, 'gross_annual_income', None),
            'superannuation_balance': getattr(profile, 'superannuation_balance', None),
            'total_assets': profile.total_assets if hasattr(profile, 'total_assets') else None,
            'total_monthly_liabilities': profile.total_monthly_liabilities if hasattr(profile, 'total_monthly_liabilities') else None,
            'employment_status': getattr(profile, 'employment_status', ''),
            'occupation': getattr(profile, 'occupation', ''),
            'industry': getattr(profile, 'industry', ''),
        }

    @staticmethod
    def _evaluate_conditions(application) -> list:
        """Evaluate risk factors and return a list of condition dicts.

        Only called when the ML model would approve.  Each condition is a dict
        with keys: type, description, required, satisfied, satisfied_at.
        """
        conditions: list[dict] = []

        # Income verification gap
        gap = getattr(application, 'income_verification_gap', None)
        if gap is not None and gap > 0.15:
            conditions.append({
                'type': 'income_verification',
                'description': (
                    f'Income verification gap of {gap:.0%} exceeds 15% threshold. '
                    'Please provide additional income documentation.'
                ),
                'required': True,
                'satisfied': False,
                'satisfied_at': None,
            })

        # Self-employed with short tenure
        if (
            application.employment_type == 'self_employed'
            and application.employment_length < 2
        ):
            conditions.append({
                'type': 'employment_verification',
                'description': (
                    'Self-employed applicant with less than 2 years tenure. '
                    'Please provide business financials and tax returns.'
                ),
                'required': True,
                'satisfied': False,
                'satisfied_at': None,
            })

        # Home purchase without property valuation
        if application.purpose == 'home' and application.property_value is None:
            conditions.append({
                'type': 'valuation_required',
                'description': (
                    'Home loan requires an independent property valuation. '
                    'A certified valuation report must be provided.'
                ),
                'required': True,
                'satisfied': False,
                'satisfied_at': None,
            })

        # Large loan without cosigner and modest income
        loan_amount = float(application.loan_amount)
        annual_income = float(application.annual_income)
        if (
            loan_amount > 500_000
            and not application.has_cosigner
            and annual_income < 100_000
        ):
            conditions.append({
                'type': 'guarantor_needed',
                'description': (
                    f'Loan amount ${loan_amount:,.0f} exceeds $500,000 without a '
                    f'co-signer and annual income ${annual_income:,.0f} is below $100,000. '
                    'A guarantor is required.'
                ),
                'required': True,
                'satisfied': False,
                'satisfied_at': None,
            })

        return conditions

    def orchestrate(self, application_id):
        """Run prediction -> email -> bias check -> NBO for a loan application."""
        start_time = time.time()
        logger.info('Starting pipeline for application %s', application_id)

        with transaction.atomic():
            application = (
                LoanApplication.objects
                .select_for_update()
                .select_related('applicant')
                .get(pk=application_id)
            )
            if application.status == 'processing':
                # If processing for more than 10 minutes, treat as stale/stuck.
                # Must exceed Celery soft_time_limit (540s / 9min) to avoid
                # race conditions where a slow-but-alive task is treated as stale.
                from django.utils import timezone as tz
                stale_threshold = tz.now() - tz.timedelta(minutes=10)
                if application.updated_at > stale_threshold:
                    raise ValueError('Pipeline already running for this application')
                logger.warning(
                    'Application %s: stale processing status (updated_at=%s), resetting',
                    application_id, application.updated_at,
                )
                # Mark any zombie agent runs as failed
                AgentRun.objects.filter(
                    application=application, status__in=('pending', 'running'),
                ).update(status='failed', error='Stale pipeline — automatically cleared')
            application.status = 'processing'
            application.save(update_fields=['status'])

        # Refetch with profile (nullable) outside the lock — select_for_update
        # cannot be combined with outer joins on nullable relations in PostgreSQL.
        application = (
            LoanApplication.objects
            .select_related('applicant__profile')
            .get(pk=application_id)
        )
        profile_context = self._build_profile_context(application)

        agent_run = AgentRun.objects.create(
            application=application,
            status='running',
            steps=[],
        )

        steps = []
        waterfall = []
        prediction_result = None
        email_result = None
        generated_email = None

        # Step 0: Fraud Detection / Velocity Checks
        step = self._start_step('fraud_check')
        try:
            fraud_service = FraudDetectionService()
            fraud_result = fraud_service.run_checks(application)

            FraudCheck.objects.create(
                application=application,
                passed=fraud_result['passed'],
                risk_score=fraud_result['risk_score'],
                checks=fraud_result['checks'],
                flagged_reasons=fraud_result['flagged_reasons'],
            )

            fraud_status = 'pass' if fraud_result['passed'] else 'fail'
            fraud_reason = 'FRAUD_CLEAR' if fraud_result['passed'] else 'FRAUD_VELOCITY'
            fraud_detail = 'No fraud indicators detected' if fraud_result['passed'] else \
                f'Fraud flags: {"; ".join(fraud_result["flagged_reasons"])}'
            waterfall.append(self._waterfall_entry(
                'fraud_check', fraud_status, fraud_reason, fraud_detail,
            ))

            step = self._complete_step(step, result_summary={
                'passed': fraud_result['passed'],
                'risk_score': fraud_result['risk_score'],
                'flagged_reasons': fraud_result['flagged_reasons'],
            })
            logger.info('Application %s: fraud check passed=%s risk_score=%.2f',
                        application_id, fraud_result['passed'], fraud_result['risk_score'])
        except Exception as e:
            logger.critical('Application %s: UNEXPECTED failure at fraud_check: %s', application_id, e, exc_info=True)
            waterfall.append(self._waterfall_entry(
                'fraud_check', 'skip', 'FRAUD_CHECK_ERROR',
                f'Fraud check infrastructure failure: {e}',
            ))
            step = self._fail_step(step, str(e), failure_category=None)
            # Fraud check infra failure — continue to ML prediction rather than blocking
            fraud_result = {'passed': True, 'risk_score': 0.0, 'checks': [], 'flagged_reasons': []}

        steps.append(step)

        # If fraud check failed, set to review and skip ML prediction
        if not fraud_result['passed']:
            waterfall.append(self._waterfall_entry(
                'final_decision', 'fail', 'ESCALATED_FRAUD',
                f'Fraud check failed, escalated to review',
            ))
            self._save_waterfall(application, waterfall)

            application_note = f'Fraud flags: {"; ".join(fraud_result["flagged_reasons"])}'
            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(
                    status='review',
                    notes=application_note,
                )
            self._finalize_run(agent_run, steps, start_time, error=application_note)
            logger.warning('Application %s: fraud check failed — sent to review', application_id)
            return agent_run

        # Step 1: ML Prediction
        step = self._start_step('ml_prediction')
        try:
            predictor = ModelPredictor()
            prediction_result = predictor.predict(application)

            PredictionLog.objects.create(
                model_version_id=prediction_result['model_version'],
                application=application,
                prediction=prediction_result['prediction'],
                probability=prediction_result['probability'],
                feature_importances=prediction_result['feature_importances'],
                processing_time_ms=prediction_result['processing_time_ms'],
            )

            from apps.loans.models import AuditLog
            AuditLog.objects.create(
                action='prediction_completed',
                resource_type='LoanApplication',
                resource_id=str(application.pk),
                details={
                    'prediction': prediction_result['prediction'],
                    'probability': round(prediction_result['probability'], 4),
                    'requires_human_review': prediction_result.get('requires_human_review', False),
                },
            )

            LoanDecision.objects.update_or_create(
                application=application,
                defaults={
                    'decision': prediction_result['prediction'],
                    'confidence': prediction_result['probability'],
                    'feature_importances': prediction_result['feature_importances'],
                    'shap_values': prediction_result.get('shap_values', {}),
                    'model_version': prediction_result['model_version'],
                },
            )

            # Record policy-level waterfall entries derived from application data
            if application.has_bankruptcy:
                waterfall.append(self._waterfall_entry(
                    'policy_rules', 'fail', 'BANKRUPTCY_FLAG',
                    'Applicant has undischarged bankruptcy or within 7-year window',
                ))
            else:
                waterfall.append(self._waterfall_entry(
                    'policy_rules', 'pass', 'BANKRUPTCY_CLEAR',
                    'No bankruptcy flag on application',
                ))

            dti = float(application.debt_to_income)
            dti_cap = 6.0
            if dti > dti_cap:
                waterfall.append(self._waterfall_entry(
                    'policy_rules', 'fail', 'DTI_EXCEEDED',
                    f'Debt-to-income ratio {dti:.2f} exceeds cap of {dti_cap}',
                ))
            else:
                waterfall.append(self._waterfall_entry(
                    'policy_rules', 'pass', 'DTI_WITHIN_LIMIT',
                    f'Debt-to-income ratio {dti:.2f} within cap of {dti_cap}',
                ))

            # ML prediction waterfall entry
            prob = prediction_result['probability']
            ml_result = 'pass' if prediction_result['prediction'] == 'approved' else 'fail'
            ml_reason = 'MODEL_APPROVED' if ml_result == 'pass' else 'MODEL_DENIED'
            waterfall.append(self._waterfall_entry(
                'ml_prediction', ml_result, ml_reason,
                f'Model prediction: {prediction_result["prediction"]} '
                f'(confidence={prob:.4f}, model={prediction_result["model_version"]})',
            ))

            step = self._complete_step(step, result_summary={
                'prediction': prediction_result['prediction'],
                'probability': prediction_result['probability'],
            })
            logger.info('Application %s: prediction=%s prob=%.3f',
                        application_id, prediction_result['prediction'], prediction_result['probability'])
        except (MLPredictionError, ConnectionError, TimeoutError) as e:
            logger.error('Application %s: ML prediction failed: %s', application_id, e)
            waterfall.append(self._waterfall_entry(
                'ml_prediction', 'fail', 'MODEL_ERROR',
                f'ML prediction failed: {e}',
            ))
            self._save_waterfall(application, waterfall)
            step = self._fail_step(step, str(e), failure_category='transient')
            self._finalize_run(agent_run, steps + [step], start_time, error=str(e))
            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(status='review')
            return agent_run
        except Exception as e:
            logger.critical('Application %s: UNEXPECTED failure at ml_prediction: %s', application_id, e, exc_info=True)
            waterfall.append(self._waterfall_entry(
                'ml_prediction', 'fail', 'MODEL_ERROR',
                f'ML prediction unexpected failure: {e}',
            ))
            self._save_waterfall(application, waterfall)
            step = self._fail_step(step, str(e), failure_category=None)
            self._finalize_run(agent_run, steps + [step], start_time, error=str(e))
            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(status='review')
            return agent_run

        steps.append(step)
        decision = prediction_result['prediction']

        # Step 1b: Conditional approval — check for risk factors that require
        # conditions before full approval.  Only applies when the ML model
        # would approve; denied applications skip this entirely.
        conditions = []
        if decision == 'approved':
            conditions = self._evaluate_conditions(application)
            if conditions:
                decision = 'conditional'
                with transaction.atomic():
                    LoanApplication.objects.filter(pk=application.pk).update(
                        conditions=conditions,
                        conditions_met=False,
                    )
                # Update the LoanDecision to reflect conditional status
                LoanDecision.objects.filter(application=application).update(
                    decision='approved',
                    reasoning=(
                        'Conditionally approved — conditions: '
                        + ', '.join(c['type'] for c in conditions)
                    ),
                )
                waterfall.append(self._waterfall_entry(
                    'conditional_check', 'conditional', 'CONDITIONAL_APPROVAL',
                    f'Approved subject to {len(conditions)} condition(s): '
                    + ', '.join(c['type'] for c in conditions),
                ))
                logger.info(
                    'Application %s: conditional approval with %d condition(s)',
                    application_id, len(conditions),
                )

        # Step 2: Generate Email
        step = self._start_step('email_generation')
        try:
            generator = EmailGenerator()
            email_result = generator.generate(
                application, decision,
                confidence=prediction_result['probability'],
                profile_context=profile_context,
            )

            generated_email = EmailPersistenceService.save_generated_email(application, decision, email_result)
            EmailPersistenceService.save_guardrail_logs(generated_email, email_result.get('guardrail_results', []))

            email_status = 'pass' if email_result['passed_guardrails'] else 'conditional'
            waterfall.append(self._waterfall_entry(
                'email_generation', email_status, 'EMAIL_GENERATED',
                f'Email generated (guardrails_passed={email_result["passed_guardrails"]}, '
                f'template_fallback={email_result.get("template_fallback", False)})',
            ))

            step = self._complete_step(step, result_summary={
                'subject': email_result['subject'],
                'passed_guardrails': email_result['passed_guardrails'],
                'template_fallback': email_result.get('template_fallback', False),
            })
        except (LLMServiceError, ConnectionError, TimeoutError) as e:
            logger.error('Application %s: email generation failed: %s', application_id, e)
            waterfall.append(self._waterfall_entry(
                'email_generation', 'fail', 'EMAIL_ERROR',
                f'Email generation failed: {e}',
            ))
            self._save_waterfall(application, waterfall)
            step = self._fail_step(step, str(e), failure_category='transient')
            steps.append(step)
            self._finalize_run(agent_run, steps, start_time, error=str(e))
            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(status=decision)
            return agent_run
        except Exception as e:
            logger.critical('Application %s: UNEXPECTED failure at email_generation: %s', application_id, e, exc_info=True)
            waterfall.append(self._waterfall_entry(
                'email_generation', 'fail', 'EMAIL_ERROR',
                f'Email generation unexpected failure: {e}',
            ))
            self._save_waterfall(application, waterfall)
            step = self._fail_step(step, str(e), failure_category=None)
            steps.append(step)
            self._finalize_run(agent_run, steps, start_time, error=str(e))
            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(status=decision)
            return agent_run

        steps.append(step)

        # Step 3: Bias Check
        step = self._start_step('bias_check')
        try:
            bias_detector = BiasDetector()
            context = {
                'loan_amount': float(application.loan_amount),
                'purpose': application.get_purpose_display(),
                'decision': decision,
            }
            bias_result = bias_detector.analyze(email_result['body'], context)

            BiasReport.objects.create(
                agent_run=agent_run,
                email=generated_email,
                bias_score=bias_result['score'],
                deterministic_score=bias_result.get('deterministic_score'),
                llm_raw_score=bias_result.get('llm_raw_score'),
                score_source=bias_result.get('score_source', 'composite'),
                categories=bias_result['categories'],
                analysis=bias_result['analysis'],
                flagged=bias_result['flagged'],
                requires_human_review=bias_result['requires_human_review'],
            )

            step = self._complete_step(step, result_summary={
                'bias_score': bias_result['score'],
                'flagged': bias_result['flagged'],
            })
        except (LLMServiceError, ConnectionError, TimeoutError) as e:
            logger.error('Application %s: bias check failed: %s', application_id, e)
            step = self._fail_step(step, str(e), failure_category='transient')
            # With retry logic inside BiasDetector.analyze(), reaching here means
            # a fundamental failure (e.g., missing API key, prescreen code bug).
            # Default to moderate score that triggers AI review rather than
            # auto-escalating to human queue on every transient failure.
            bias_result = {'score': 65, 'flagged': True, 'requires_human_review': False,
                           'categories': [], 'analysis': f'Bias check infrastructure error: {e}'}
        except Exception as e:
            logger.critical('Application %s: UNEXPECTED failure at bias_check: %s', application_id, e, exc_info=True)
            step = self._fail_step(step, str(e), failure_category=None)
            bias_result = {'score': 65, 'flagged': True, 'requires_human_review': False,
                           'categories': [], 'analysis': f'Bias check infrastructure error: {e}'}

        steps.append(step)

        # Waterfall entry for bias check
        bias_flagged = bias_result.get('flagged', False)
        waterfall.append(self._waterfall_entry(
            'bias_check',
            'fail' if bias_flagged else 'pass',
            'BIAS_FLAGGED' if bias_flagged else 'BIAS_CLEAR',
            f'Bias score={bias_result.get("score", 0)}, flagged={bias_flagged}',
        ))

        # Step 4: Handle bias results
        bias_score = bias_result.get('score', 0)
        bias_threshold_pass = getattr(settings, 'BIAS_THRESHOLD_PASS', 60)
        bias_threshold_review = getattr(settings, 'BIAS_THRESHOLD_REVIEW', 80)

        # Score above review threshold: Severe bias — escalate directly to human
        if bias_score > bias_threshold_review:
            waterfall.append(self._waterfall_entry(
                'final_decision', 'fail', 'ESCALATED_SEVERE_BIAS',
                f'Severe bias detected (score {bias_score} > {bias_threshold_review}), escalated to human review',
            ))
            self._save_waterfall(application, waterfall)

            step = self._start_step('human_escalation_severe_bias')
            step = self._complete_step(step, result_summary={
                'bias_score': bias_score,
                'reason': f'Severe bias detected (score > {bias_threshold_review}), escalated directly to human reviewer',
            })
            steps.append(step)
            logger.warning('Application %s: severe bias (score=%s), escalating', application_id, bias_score)

            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(status='review')
            agent_run.status = 'escalated'
            self._finalize_run(agent_run, steps, start_time)
            return agent_run

        # Moderate bias — AI Email Reviewer gets second opinion
        if bias_threshold_pass < bias_score <= bias_threshold_review:
            step = self._start_step('ai_email_review')
            review_result = {'approved': False}
            try:
                reviewer = AIEmailReviewer()
                review_result = reviewer.review(email_result['body'], bias_result, context)

                latest_bias_report = agent_run.bias_reports.order_by('-created_at').first()
                if latest_bias_report:
                    latest_bias_report.ai_review_approved = review_result['approved']
                    latest_bias_report.ai_review_reasoning = review_result['reasoning']
                    latest_bias_report.save(update_fields=['ai_review_approved', 'ai_review_reasoning'])

                step = self._complete_step(step, result_summary={
                    'approved': review_result['approved'],
                    'confidence': review_result['confidence'],
                })
            except (LLMServiceError, ConnectionError, TimeoutError) as e:
                logger.error('Application %s: AI email review failed: %s', application_id, e)
                step = self._fail_step(step, str(e), failure_category='transient')
                review_result = {'approved': False}
            except Exception as e:
                logger.critical('Application %s: UNEXPECTED failure at ai_email_review: %s', application_id, e, exc_info=True)
                step = self._fail_step(step, str(e), failure_category=None)
                review_result = {'approved': False}

            steps.append(step)

            ai_approved = review_result.get('approved', False)
            ai_confidence = review_result.get('confidence', 0.0)

            if not ai_approved:
                # AI reviewer confirmed bias — escalate to human
                waterfall.append(self._waterfall_entry(
                    'final_decision', 'fail', 'ESCALATED_BIAS_CONFIRMED',
                    'AI reviewer confirmed potential bias, escalated to human review',
                ))
                self._save_waterfall(application, waterfall)

                step = self._start_step('human_escalation')
                step = self._complete_step(step, result_summary={
                    'bias_score': bias_score,
                    'reason': 'AI reviewer confirmed potential bias, escalated to human reviewer',
                })
                steps.append(step)
                logger.warning('Application %s: AI reviewer confirmed bias, escalating', application_id)

                with transaction.atomic():
                    LoanApplication.objects.filter(pk=application.pk).update(status='review')
                agent_run.status = 'escalated'
                self._finalize_run(agent_run, steps, start_time)
                return agent_run

            if ai_approved and ai_confidence < 0.7:
                # Low confidence approval — escalate for safety
                waterfall.append(self._waterfall_entry(
                    'final_decision', 'fail', 'ESCALATED_LOW_CONFIDENCE',
                    f'AI reviewer approved with low confidence ({ai_confidence:.2f} < 0.70), escalated for safety',
                ))
                self._save_waterfall(application, waterfall)

                step = self._start_step('human_escalation_low_confidence')
                step = self._complete_step(step, result_summary={
                    'bias_score': bias_score,
                    'ai_confidence': ai_confidence,
                    'reason': f'AI reviewer approved but with low confidence ({ai_confidence:.2f} < 0.70), escalated for safety',
                })
                steps.append(step)
                logger.warning('Application %s: low-confidence AI approval (%.2f), escalating',
                               application_id, ai_confidence)

                with transaction.atomic():
                    LoanApplication.objects.filter(pk=application.pk).update(status='review')
                agent_run.status = 'escalated'
                self._finalize_run(agent_run, steps, start_time)
                return agent_run

            # AI reviewer approved with high confidence — continue pipeline

        # Guardrail failure → escalate to human review (email must be checked
        # by a banker before it can be sent to the customer).
        if email_result and not email_result['passed_guardrails']:
            failed_checks = [
                r['check_name'] for r in email_result.get('guardrail_results', [])
                if not r['passed']
            ]
            waterfall.append(self._waterfall_entry(
                'final_decision', 'fail', 'ESCALATED_GUARDRAIL_FAILURE',
                f'Email guardrails failed ({", ".join(failed_checks)}), escalated to human review',
            ))
            self._save_waterfall(application, waterfall)

            logger.warning(
                'Application %s: guardrails failed after %d attempts — escalating to human review. '
                'Failed checks: %s',
                application_id, email_result.get('attempt_number', 1), ', '.join(failed_checks),
            )
            step = self._start_step('email_delivery')
            step = self._complete_step(step, result_summary={
                'sent': False,
                'reason': 'Guardrails failed — escalated to human review',
                'failed_guardrails': failed_checks,
            })
            steps.append(step)

            with transaction.atomic():
                LoanApplication.objects.filter(pk=application.pk).update(status='review')
            agent_run.status = 'escalated'
            agent_run.error = f'Email guardrails failed: {", ".join(failed_checks)}'
            self._finalize_run(agent_run, steps, start_time)
            return agent_run

        # Send decision email to customer
        step = self._start_step('email_delivery')
        try:
            from apps.email_engine.services.sender import send_decision_email
            recipient = application.applicant.email
            if recipient and generated_email:
                send_result = send_decision_email(recipient, email_result['subject'], email_result['body'])
                if send_result['sent']:
                    step = self._complete_step(step, result_summary={
                        'sent': True,
                        'recipient': recipient,
                    })
                else:
                    step = self._fail_step(step, send_result.get('error', 'Send failed'))
            else:
                step = self._complete_step(step, result_summary={
                    'sent': False,
                    'reason': 'No recipient email or generated email missing',
                })
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.error('Application %s: email delivery failed: %s', application_id, e)
            step = self._fail_step(step, str(e), failure_category='transient')
        except Exception as e:
            logger.critical('Application %s: UNEXPECTED failure at email_delivery: %s', application_id, e, exc_info=True)
            step = self._fail_step(step, str(e), failure_category=None)
        steps.append(step)

        # Step 5: NBO + Marketing pipeline (if denied)
        if decision == 'denied':
            denial_reasons = ''
            if prediction_result and prediction_result.get('feature_importances'):
                top_factors = sorted(
                    prediction_result['feature_importances'].items(),
                    key=lambda x: x[1], reverse=True
                )[:3]
                denial_reasons = ', '.join(f'{k}: {v:.3f}' for k, v in top_factors)

            steps = self._run_nbo_and_marketing_pipeline(
                application, agent_run, steps, denial_reasons, profile_context,
            )

        # Final decision waterfall entry
        final_reason_map = {
            'approved': 'APPROVED',
            'conditional': 'CONDITIONAL_APPROVED',
            'denied': 'DENIED',
        }
        final_reason = final_reason_map.get(decision, decision.upper())
        waterfall.append(self._waterfall_entry(
            'final_decision', 'pass' if decision in ('approved', 'conditional') else 'fail',
            final_reason,
            f'Pipeline completed with decision: {decision}',
        ))
        self._save_waterfall(application, waterfall)

        # Finalize — update application status to final decision
        with transaction.atomic():
            rows = LoanApplication.objects.filter(pk=application.pk).update(status=decision)
            if rows == 0:
                logger.error('Application %s: status update to %s affected 0 rows', application_id, decision)
            else:
                logger.info('Application %s: status updated to %s', application_id, decision)
        self._finalize_run(agent_run, steps, start_time)
        logger.info('Application %s: pipeline completed with decision=%s', application_id, decision)

        return agent_run

    def resume_after_review(self, agent_run_id, reviewer='', note=''):
        """Pick up an escalated pipeline after a human approves or denies it."""
        start_time = time.time()
        logger.info('Resuming agent run %s after human review', agent_run_id)

        with transaction.atomic():
            agent_run = AgentRun.objects.select_for_update().select_related(
                'application__applicant', 'application__decision',
            ).get(pk=agent_run_id)

            if agent_run.status != 'escalated':
                raise ValueError(
                    f'Cannot resume agent run with status {agent_run.status!r} (expected "escalated")'
                )

            application = agent_run.application

            # Lock application to prevent two simultaneous reviews from resuming
            LoanApplication.objects.select_for_update().get(pk=application.pk)
            if application.status != 'review':
                raise ValueError(
                    f'Cannot resume: application status is {application.status!r} (expected "review")'
                )

            try:
                _ = application.decision
            except LoanDecision.DoesNotExist:
                raise ValueError(f'No decision found for application {application.id}')

            decision = application.decision.decision

        # Refetch with profile outside the lock (nullable relation can't be in select_for_update)
        application = (
            LoanApplication.objects
            .select_related('applicant__profile', 'decision')
            .get(pk=application.pk)
        )
        profile_context = self._build_profile_context(application)
        steps = agent_run.steps or []

        # Record the human approval
        step = self._start_step('human_review_approved')
        step = self._complete_step(step, result_summary={
            'reviewer': reviewer,
            'note': note,
            'action': 'approve',
        })
        steps.append(step)

        if decision == 'approved':
            # Human approved an escalated application — re-generate and send approval email
            step = self._start_step('email_generation')
            try:
                generator = EmailGenerator()
                email_result = generator.generate(
                    application, 'approved',
                    confidence=application.decision.confidence,
                    profile_context=profile_context,
                )

                generated_email = EmailPersistenceService.save_generated_email(application, 'approved', email_result)
                EmailPersistenceService.save_guardrail_logs(generated_email, email_result.get('guardrail_results', []))

                step = self._complete_step(step, result_summary={
                    'subject': email_result['subject'],
                    'passed_guardrails': email_result['passed_guardrails'],
                })
            except (LLMServiceError, ConnectionError, TimeoutError) as e:
                logger.error('Agent run %s: approval email generation failed: %s', agent_run_id, e)
                step = self._fail_step(step, str(e), failure_category='transient')
                email_result = None
            except Exception as e:
                logger.critical('Agent run %s: UNEXPECTED failure at approval email_generation: %s', agent_run_id, e, exc_info=True)
                step = self._fail_step(step, str(e), failure_category=None)
                email_result = None
            steps.append(step)

            # Guardrail failure on resume → re-escalate for human review
            if email_result and not email_result.get('passed_guardrails'):
                failed_checks = [
                    r['check_name'] for r in email_result.get('guardrail_results', [])
                    if not r['passed']
                ]
                logger.warning(
                    'Agent run %s: approval email guardrails failed on resume — re-escalating. '
                    'Failed checks: %s',
                    agent_run_id, ', '.join(failed_checks),
                )
                step = self._start_step('email_delivery')
                step = self._complete_step(step, result_summary={
                    'sent': False,
                    'reason': 'Guardrails failed on resume — re-escalated to human review',
                    'failed_guardrails': failed_checks,
                })
                steps.append(step)
                agent_run.status = 'escalated'
                agent_run.error = f'Email guardrails failed on resume: {", ".join(failed_checks)}'
                self._finalize_run(agent_run, steps, start_time)
                return agent_run

            # Send the approval email
            if email_result:
                step = self._start_step('email_delivery')
                try:
                    from apps.email_engine.services.sender import send_decision_email
                    recipient = application.applicant.email
                    if recipient:
                        send_result = send_decision_email(recipient, email_result['subject'], email_result['body'])
                        if send_result['sent']:
                            step = self._complete_step(step, result_summary={
                                'sent': True,
                                'recipient': recipient,
                            })
                        else:
                            step = self._fail_step(step, send_result.get('error', 'Send failed'))
                    else:
                        step = self._complete_step(step, result_summary={
                            'sent': False,
                            'reason': 'No recipient email',
                        })
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.error('Agent run %s: approval email delivery failed: %s', agent_run_id, e)
                    step = self._fail_step(step, str(e), failure_category='transient')
                except Exception as e:
                    logger.critical('Agent run %s: UNEXPECTED failure at approval email_delivery: %s', agent_run_id, e, exc_info=True)
                    step = self._fail_step(step, str(e), failure_category=None)
                steps.append(step)

        elif decision == 'denied':
            # Extract denial reasons from stored feature importances
            denial_reasons = ''
            if hasattr(application, 'decision') and application.decision.feature_importances:
                top_factors = sorted(
                    application.decision.feature_importances.items(),
                    key=lambda x: x[1], reverse=True
                )[:3]
                denial_reasons = ', '.join(f'{k}: {v:.3f}' for k, v in top_factors)

            steps = self._run_nbo_and_marketing_pipeline(
                application, agent_run, steps, denial_reasons, profile_context,
            )

        # Finalize — _finalize_run sets status to 'completed' internally
        with transaction.atomic():
            LoanApplication.objects.filter(pk=application.pk).update(status=decision)
        self._finalize_run(agent_run, steps, start_time)
        logger.info('Agent run %s: resumed and completed with decision=%s', agent_run_id, decision)

        return agent_run

    def _run_nbo_and_marketing_pipeline(self, application, agent_run, steps, denial_reasons, profile_context):
        """Run NBO generation -> marketing message -> marketing email -> bias check -> send.

        Shared by both orchestrate() and resume_after_review() for denied applications.
        """
        nbo_result = None
        nbo_generator = NextBestOfferGenerator()

        # NBO generation
        step = self._start_step('next_best_offers')
        try:
            nbo_result = nbo_generator.generate(application, denial_reasons=denial_reasons)

            nbo_record = NextBestOffer.objects.create(
                agent_run=agent_run,
                application=application,
                offers=nbo_result['offers'],
                analysis=nbo_result['analysis'],
                customer_retention_score=nbo_result.get('customer_retention_score', 0),
                loyalty_factors=nbo_result.get('loyalty_factors', []),
                personalized_message=nbo_result.get('personalized_message', ''),
            )

            step = self._complete_step(step, result_summary={
                'num_offers': len(nbo_result['offers']),
                'customer_retention_score': nbo_result.get('customer_retention_score', 0),
            })
        except (LLMServiceError, ConnectionError, TimeoutError) as e:
            logger.error('Application %s: NBO generation failed: %s', application.pk, e)
            step = self._fail_step(step, str(e), failure_category='transient')
        except Exception as e:
            logger.critical('Application %s: UNEXPECTED failure at next_best_offers: %s', application.pk, e, exc_info=True)
            step = self._fail_step(step, str(e), failure_category=None)

        steps.append(step)

        if not nbo_result or not nbo_result.get('offers'):
            logger.warning('Application %s: no NBO offers generated — skipping marketing email pipeline', application.pk)

        # Marketing Message Generation (if NBO succeeded)
        if nbo_result and nbo_result.get('offers'):
            step = self._start_step('marketing_message_generation')
            try:
                marketing_result = nbo_generator.generate_marketing_message(
                    application, nbo_result['offers'], denial_reasons=denial_reasons,
                )
                nbo_record.marketing_message = marketing_result['marketing_message']
                nbo_record.save(update_fields=['marketing_message'])

                step = self._complete_step(step, result_summary={
                    'message_length': len(marketing_result['marketing_message']),
                    'generation_time_ms': marketing_result['generation_time_ms'],
                })
            except (LLMServiceError, ConnectionError, TimeoutError) as e:
                logger.error('Application %s: marketing message failed: %s', application.pk, e)
                step = self._fail_step(step, str(e), failure_category='transient')
            except Exception as e:
                logger.critical('Application %s: UNEXPECTED failure at marketing_message_generation: %s', application.pk, e, exc_info=True)
                step = self._fail_step(step, str(e), failure_category=None)

            steps.append(step)

        # Marketing Agent Email (if NBO succeeded)
        if nbo_result and nbo_result.get('offers'):
            step = self._start_step('marketing_email_generation')
            email_result_marketing = None
            try:
                marketing_agent = MarketingAgent()
                email_result_marketing = marketing_agent.generate(
                    application, nbo_result, denial_reasons=denial_reasons,
                )

                step = self._complete_step(step, result_summary={
                    'subject': email_result_marketing['subject'],
                    'passed_guardrails': email_result_marketing['passed_guardrails'],
                    'attempt_number': email_result_marketing['attempt_number'],
                    'generation_time_ms': email_result_marketing['generation_time_ms'],
                })
            except (LLMServiceError, ConnectionError, TimeoutError) as e:
                logger.error('Application %s: marketing email generation failed: %s', application.pk, e)
                step = self._fail_step(step, str(e), failure_category='transient')
            except Exception as e:
                logger.critical('Application %s: UNEXPECTED failure at marketing_email_generation: %s', application.pk, e, exc_info=True)
                step = self._fail_step(step, str(e), failure_category=None)

            steps.append(step)

            # Marketing bias check → save → send
            # Always save the marketing email to DB regardless of bias outcome
            if email_result_marketing:
                send_approved = False
                if email_result_marketing.get('passed_guardrails'):
                    try:
                        steps, send_approved = self._run_marketing_bias_check(
                            email_result_marketing, application, agent_run, steps,
                        )
                    except (LLMServiceError, ConnectionError, TimeoutError) as e:
                        logger.error('Application %s: marketing bias check failed: %s', application.pk, e)
                        send_approved = False
                    except Exception as e:
                        logger.critical('Application %s: UNEXPECTED failure at marketing_bias_check: %s', application.pk, e, exc_info=True)
                        send_approved = False

                logger.info('Application %s: marketing send_approved=%s', application.pk, send_approved)

                # Single save point for MarketingEmail
                marketing_email_obj = MarketingEmail.objects.create(
                    agent_run=agent_run,
                    application=application,
                    subject=email_result_marketing['subject'],
                    body=email_result_marketing['body'],
                    prompt_used=email_result_marketing['prompt_used'],
                    generation_time_ms=email_result_marketing['generation_time_ms'],
                    attempt_number=email_result_marketing['attempt_number'],
                    passed_guardrails=email_result_marketing['passed_guardrails'],
                    guardrail_results=email_result_marketing['guardrail_results'],
                )

                # Link the marketing BiasReport to the MarketingEmail record
                BiasReport.objects.filter(
                    agent_run=agent_run,
                    report_type='marketing',
                    marketing_email__isnull=True,
                ).update(marketing_email=marketing_email_obj)

                # Send if approved
                if send_approved:
                    step = self._start_step('marketing_email_delivery')
                    try:
                        from apps.email_engine.services.sender import send_decision_email
                        recipient = application.applicant.email
                        if recipient:
                            send_result = send_decision_email(
                                recipient,
                                email_result_marketing['subject'],
                                email_result_marketing['body'],
                            )
                            if send_result['sent']:
                                step = self._complete_step(step, result_summary={
                                    'sent': True,
                                    'recipient': recipient,
                                })
                            else:
                                step = self._fail_step(step, send_result.get('error', 'Send failed'))
                        else:
                            step = self._complete_step(step, result_summary={
                                'sent': False,
                                'reason': 'No recipient email',
                            })
                    except (ConnectionError, TimeoutError, OSError) as e:
                        logger.error('Application %s: marketing email delivery failed: %s', application.pk, e)
                        step = self._fail_step(step, str(e), failure_category='transient')
                    except Exception as e:
                        logger.critical('Application %s: UNEXPECTED failure at marketing_email_delivery: %s', application.pk, e, exc_info=True)
                        step = self._fail_step(step, str(e), failure_category=None)

                    steps.append(step)

        return steps

    def _run_marketing_bias_check(self, email_result_marketing, application, agent_run, steps):
        """Run bias analysis on a marketing email. Returns (steps, send_approved)."""
        marketing_context = {
            'loan_amount': float(application.loan_amount),
            'purpose': application.get_purpose_display(),
            'decision': 'denied',
        }

        bias_threshold_pass = getattr(settings, 'MARKETING_BIAS_THRESHOLD_PASS', 50)
        bias_threshold_review = getattr(settings, 'MARKETING_BIAS_THRESHOLD_REVIEW', 70)

        step = self._start_step('marketing_bias_check')
        marketing_bias_result = {'score': 100, 'flagged': True, 'requires_human_review': True}
        try:
            detector = MarketingBiasDetector()
            marketing_bias_result = detector.analyze(
                email_result_marketing['body'], marketing_context,
            )

            # Create a BiasReport record for the marketing email bias check
            BiasReport.objects.create(
                agent_run=agent_run,
                report_type='marketing',
                bias_score=marketing_bias_result['score'],
                deterministic_score=marketing_bias_result.get('deterministic_score'),
                llm_raw_score=marketing_bias_result.get('llm_raw_score'),
                score_source=marketing_bias_result.get('score_source', 'composite'),
                categories=marketing_bias_result['categories'],
                analysis=marketing_bias_result['analysis'],
                flagged=marketing_bias_result['flagged'],
                requires_human_review=marketing_bias_result['requires_human_review'],
            )

            step = self._complete_step(step, result_summary={
                'bias_score': marketing_bias_result['score'],
                'flagged': marketing_bias_result['flagged'],
            })
        except (LLMServiceError, ConnectionError, TimeoutError) as e:
            logger.error('Application %s: marketing bias check failed: %s', application.pk, e)
            step = self._fail_step(step, str(e), failure_category='transient')
            marketing_bias_result = {'score': 100, 'flagged': True, 'requires_human_review': True}
        except Exception as e:
            logger.critical('Application %s: UNEXPECTED failure at marketing_bias_check: %s', application.pk, e, exc_info=True)
            step = self._fail_step(step, str(e), failure_category=None)
            marketing_bias_result = {'score': 100, 'flagged': True, 'requires_human_review': True}
        steps.append(step)

        marketing_bias_score = marketing_bias_result.get('score', 100)

        if marketing_bias_score > bias_threshold_review:
            logger.warning('Application %s: marketing email blocked — bias score %s > review threshold %s',
                           application.pk, marketing_bias_score, bias_threshold_review)
            step = self._start_step('marketing_email_blocked')
            step = self._complete_step(step, result_summary={
                'bias_score': marketing_bias_score,
                'reason': f'Marketing email blocked: bias score {marketing_bias_score} exceeds threshold {bias_threshold_review}',
            })
            steps.append(step)
            return steps, False

        if bias_threshold_pass < marketing_bias_score <= bias_threshold_review:
            step = self._start_step('marketing_ai_review')
            review_result = {'approved': False}
            try:
                reviewer = MarketingEmailReviewer()
                review_result = reviewer.review(
                    email_result_marketing['body'], marketing_bias_result, marketing_context,
                )
                step = self._complete_step(step, result_summary={
                    'approved': review_result['approved'],
                    'confidence': review_result['confidence'],
                })
            except (LLMServiceError, ConnectionError, TimeoutError) as e:
                logger.error('Application %s: marketing AI review failed: %s', application.pk, e)
                step = self._fail_step(step, str(e), failure_category='transient')
                review_result = {'approved': False}
            except Exception as e:
                logger.critical('Application %s: UNEXPECTED failure at marketing_ai_review: %s', application.pk, e, exc_info=True)
                step = self._fail_step(step, str(e), failure_category=None)
                review_result = {'approved': False}
            steps.append(step)

            if not review_result.get('approved', False):
                logger.warning('Application %s: marketing email blocked by senior reviewer', application.pk)
                step = self._start_step('marketing_email_blocked')
                step = self._complete_step(step, result_summary={
                    'bias_score': marketing_bias_score,
                    'reason': 'Senior reviewer blocked marketing email after bias flag',
                })
                steps.append(step)
                return steps, False

        logger.info('Application %s: marketing email approved for sending', application.pk)
        return steps, True

    def _start_step(self, step_name):
        return {
            'step_name': step_name,
            'status': 'running',
            'started_at': datetime.now(timezone.utc).isoformat(),
            'completed_at': None,
            'duration_ms': None,
            'timeout_ms': STEP_TIMEOUT_BUDGETS_MS.get(step_name, 120_000),
            'result_summary': None,
            'error': None,
            'failure_category': None,
        }

    def _complete_step(self, step, result_summary=None):
        now = datetime.now(timezone.utc)
        step['status'] = 'completed'
        step['completed_at'] = now.isoformat()
        started = datetime.fromisoformat(step['started_at'])
        step['duration_ms'] = int((now - started).total_seconds() * 1000)
        step['result_summary'] = result_summary
        timeout_ms = step.get('timeout_ms', 120_000)
        if step['duration_ms'] > timeout_ms:
            logger.warning(
                'Step %s exceeded timeout budget: %dms > %dms',
                step['step_name'], step['duration_ms'], timeout_ms,
            )
        return step

    def _fail_step(self, step, error, failure_category=None):
        now = datetime.now(timezone.utc)
        step['status'] = 'failed'
        step['completed_at'] = now.isoformat()
        started = datetime.fromisoformat(step['started_at'])
        step['duration_ms'] = int((now - started).total_seconds() * 1000)
        step['error'] = error
        step['failure_category'] = failure_category or self._categorize_error(error)
        return step

    def _categorize_error(self, error):
        """Classify an error string into a failure category for monitoring."""
        error_lower = str(error).lower()
        if any(term in error_lower for term in ['timeout', 'rate limit', '429', 'timed out']):
            return 'transient'
        if any(term in error_lower for term in ['auth', '401', '403', 'not found', 'model not found', 'invalid']):
            return 'permanent'
        if any(term in error_lower for term in ['redis', 'database', 'connection refused', 'connection reset', 'broken pipe']):
            return 'infrastructure'
        return 'unknown'

    def _finalize_run(self, agent_run, steps, start_time, error=None):
        total_time = int((time.time() - start_time) * 1000)
        agent_run.steps = steps
        agent_run.total_time_ms = total_time
        if agent_run.status != 'escalated':
            agent_run.status = 'failed' if error else 'completed'
        agent_run.error = error or ''
        agent_run.save()
