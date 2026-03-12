import time
from datetime import datetime, timezone

from apps.agents.models import AgentRun, BiasReport, NextBestOffer
from apps.email_engine.models import GeneratedEmail, GuardrailLog
from apps.email_engine.services.email_generator import EmailGenerator
from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.models import PredictionLog
from apps.ml_engine.services.predictor import ModelPredictor

from .bias_detector import BiasDetector
from .next_best_offer import NextBestOfferGenerator


class PipelineOrchestrator:
    """
    Central coordination point for the full loan processing pipeline.
    Orchestrates ML prediction, email generation, bias checking, and next best offers.
    """

    MAX_BIAS_RETRIES = 2

    def orchestrate(self, application_id):
        """
        Run the full pipeline for a loan application.

        Steps:
            1. Run ML prediction
            2. Generate decision email
            3. Run bias check on email
            4. If bias detected, regenerate email (up to MAX_BIAS_RETRIES)
            5. If denied, generate next best offers
        """
        start_time = time.time()

        application = LoanApplication.objects.select_related('applicant').get(pk=application_id)
        application.status = 'processing'
        application.save(update_fields=['status'])

        agent_run = AgentRun.objects.create(
            application=application,
            status='running',
            steps=[],
        )

        steps = []
        prediction_result = None
        email_result = None
        generated_email = None

        # Step 1: ML Prediction
        step = self._start_step('ml_prediction')
        try:
            predictor = ModelPredictor()
            prediction_result = predictor.predict(application)

            # Save prediction log
            PredictionLog.objects.create(
                model_version_id=prediction_result['model_version'],
                application=application,
                prediction=prediction_result['prediction'],
                probability=prediction_result['probability'],
                feature_importances=prediction_result['feature_importances'],
                processing_time_ms=prediction_result['processing_time_ms'],
            )

            # Save loan decision
            LoanDecision.objects.update_or_create(
                application=application,
                defaults={
                    'decision': prediction_result['prediction'],
                    'confidence': prediction_result['probability'],
                    'feature_importances': prediction_result['feature_importances'],
                    'model_version': prediction_result['model_version'],
                },
            )

            step = self._complete_step(step, result_summary={
                'prediction': prediction_result['prediction'],
                'probability': prediction_result['probability'],
            })
        except Exception as e:
            step = self._fail_step(step, str(e))
            self._finalize_run(agent_run, steps + [step], start_time, error=str(e))
            application.status = 'review'
            application.save(update_fields=['status'])
            return agent_run

        steps.append(step)
        decision = prediction_result['prediction']

        # Step 2: Generate Email
        step = self._start_step('email_generation')
        try:
            generator = EmailGenerator()
            email_result = generator.generate(application, decision)

            generated_email = GeneratedEmail.objects.create(
                application=application,
                decision=decision,
                subject=email_result['subject'],
                body=email_result['body'],
                prompt_used=email_result['prompt_used'],
                model_used='claude-sonnet-4-20250514',
                generation_time_ms=email_result['generation_time_ms'],
                attempt_number=email_result['attempt_number'],
                passed_guardrails=email_result['passed_guardrails'],
            )

            for check in email_result['guardrail_results']:
                GuardrailLog.objects.create(
                    email=generated_email,
                    check_name=check['check_name'],
                    passed=check['passed'],
                    details=check['details'],
                )

            step = self._complete_step(step, result_summary={
                'subject': email_result['subject'],
                'passed_guardrails': email_result['passed_guardrails'],
            })
        except Exception as e:
            step = self._fail_step(step, str(e))
            steps.append(step)
            self._finalize_run(agent_run, steps, start_time, error=str(e))
            application.status = decision
            application.save(update_fields=['status'])
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
                categories=bias_result['categories'],
                analysis=bias_result['analysis'],
                flagged=bias_result['flagged'],
                requires_human_review=bias_result['requires_human_review'],
            )

            step = self._complete_step(step, result_summary={
                'bias_score': bias_result['score'],
                'flagged': bias_result['flagged'],
            })
        except Exception as e:
            step = self._fail_step(step, str(e))
            steps.append(step)
            # Continue even if bias check fails
            bias_result = {'score': 0, 'flagged': False}

        steps.append(step)

        # Step 4: Regenerate if bias detected
        if bias_result.get('flagged', False) and bias_result.get('score', 0) > 30:
            for retry in range(self.MAX_BIAS_RETRIES):
                step = self._start_step(f'email_regeneration_attempt_{retry + 1}')
                try:
                    email_result = generator.generate(application, decision, attempt=retry + 2)

                    generated_email = GeneratedEmail.objects.create(
                        application=application,
                        decision=decision,
                        subject=email_result['subject'],
                        body=email_result['body'],
                        prompt_used=email_result['prompt_used'],
                        model_used='claude-sonnet-4-20250514',
                        generation_time_ms=email_result['generation_time_ms'],
                        attempt_number=email_result['attempt_number'],
                        passed_guardrails=email_result['passed_guardrails'],
                    )

                    # Re-check bias
                    bias_result = bias_detector.analyze(email_result['body'], context)

                    BiasReport.objects.create(
                        agent_run=agent_run,
                        email=generated_email,
                        bias_score=bias_result['score'],
                        categories=bias_result['categories'],
                        analysis=bias_result['analysis'],
                        flagged=bias_result['flagged'],
                        requires_human_review=bias_result['requires_human_review'],
                    )

                    step = self._complete_step(step, result_summary={
                        'bias_score': bias_result['score'],
                        'flagged': bias_result['flagged'],
                    })
                    steps.append(step)

                    if not bias_result.get('flagged', False):
                        break
                except Exception as e:
                    step = self._fail_step(step, str(e))
                    steps.append(step)
                    break

        # Step 5: Next Best Offers (if denied)
        if decision == 'denied':
            step = self._start_step('next_best_offers')
            try:
                nbo_generator = NextBestOfferGenerator()
                nbo_result = nbo_generator.generate(application)

                NextBestOffer.objects.create(
                    agent_run=agent_run,
                    application=application,
                    offers=nbo_result['offers'],
                    analysis=nbo_result['analysis'],
                )

                step = self._complete_step(step, result_summary={
                    'num_offers': len(nbo_result['offers']),
                })
            except Exception as e:
                step = self._fail_step(step, str(e))

            steps.append(step)

        # Finalize
        application.status = decision
        application.save(update_fields=['status'])
        self._finalize_run(agent_run, steps, start_time)

        return agent_run

    def _start_step(self, step_name):
        return {
            'step_name': step_name,
            'status': 'running',
            'started_at': datetime.now(timezone.utc).isoformat(),
            'completed_at': None,
            'result_summary': None,
            'error': None,
        }

    def _complete_step(self, step, result_summary=None):
        step['status'] = 'completed'
        step['completed_at'] = datetime.now(timezone.utc).isoformat()
        step['result_summary'] = result_summary
        return step

    def _fail_step(self, step, error):
        step['status'] = 'failed'
        step['completed_at'] = datetime.now(timezone.utc).isoformat()
        step['error'] = error
        return step

    def _finalize_run(self, agent_run, steps, start_time, error=None):
        total_time = int((time.time() - start_time) * 1000)
        agent_run.steps = steps
        agent_run.total_time_ms = total_time
        agent_run.status = 'failed' if error else 'completed'
        agent_run.error = error or ''
        agent_run.save()
