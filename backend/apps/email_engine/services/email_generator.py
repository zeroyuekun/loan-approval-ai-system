import os
import time

import anthropic

from .guardrails import GuardrailChecker
from .prompts import APPROVAL_EMAIL_PROMPT, DENIAL_EMAIL_PROMPT


class EmailGenerator:
    """Generates loan decision emails using Claude API with guardrail checks."""

    MAX_RETRIES = 3

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))
        self.guardrail_checker = GuardrailChecker()

    def generate(self, application, decision, attempt=1):
        """
        Generate an email for the given loan application and decision.

        Args:
            application: LoanApplication instance
            decision: 'approved' or 'denied'
            attempt: current attempt number

        Returns:
            dict with subject, body, prompt_used, guardrail_results, passed_guardrails,
            generation_time_ms, attempt_number
        """
        start_time = time.time()

        applicant_name = f"{application.applicant.first_name} {application.applicant.last_name}".strip()
        if not applicant_name:
            applicant_name = application.applicant.username

        context = {
            'applicant_name': applicant_name,
            'loan_amount': float(application.loan_amount),
            'purpose': application.get_purpose_display(),
            'decision': decision,
        }

        # Build prompt
        if decision == 'approved':
            confidence = 0.0
            if hasattr(application, 'decision') and application.decision:
                confidence = application.decision.confidence
            prompt = APPROVAL_EMAIL_PROMPT.format(
                applicant_name=applicant_name,
                loan_amount=float(application.loan_amount),
                purpose=application.get_purpose_display(),
                confidence=confidence,
            )
        else:
            reasons = "Credit score below threshold, high debt-to-income ratio"
            if hasattr(application, 'decision') and application.decision:
                importances = application.decision.feature_importances
                if importances:
                    top_factors = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:3]
                    reasons = ", ".join(f"{k}: {v}" for k, v in top_factors)
            prompt = DENIAL_EMAIL_PROMPT.format(
                applicant_name=applicant_name,
                loan_amount=float(application.loan_amount),
                purpose=application.get_purpose_display(),
                reasons=reasons,
            )

        # Add retry feedback if not first attempt
        if attempt > 1:
            prompt += "\n\nIMPORTANT: Previous attempt failed guardrail checks. Please ensure compliance with all requirements."

        # Call Claude API
        response = self.client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1024,
            messages=[{'role': 'user', 'content': prompt}],
        )

        response_text = response.content[0].text
        generation_time = int((time.time() - start_time) * 1000)

        # Parse subject and body
        subject, body = self._parse_response(response_text)

        # Run guardrails
        guardrail_results = self.guardrail_checker.run_all_checks(body, context)
        all_passed = all(r['passed'] for r in guardrail_results)

        # Retry if guardrails failed and we have attempts left
        if not all_passed and attempt < self.MAX_RETRIES:
            failed_checks = [r for r in guardrail_results if not r['passed']]
            feedback = "; ".join(f"{r['check_name']}: {r['details']}" for r in failed_checks)
            prompt += f"\n\nGuardrail failures from attempt {attempt}: {feedback}"
            return self.generate(application, decision, attempt=attempt + 1)

        return {
            'subject': subject,
            'body': body,
            'prompt_used': prompt,
            'guardrail_results': guardrail_results,
            'passed_guardrails': all_passed,
            'generation_time_ms': generation_time,
            'attempt_number': attempt,
        }

    def _parse_response(self, text):
        """Parse the Claude response into subject and body."""
        lines = text.strip().split('\n')
        subject = ''
        body_start = 0

        for i, line in enumerate(lines):
            if line.lower().startswith('subject:'):
                subject = line[len('Subject:'):].strip()
                body_start = i + 1
                break

        # Skip empty lines after subject
        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1

        body = '\n'.join(lines[body_start:]).strip()

        if not subject:
            subject = 'Regarding Your Loan Application'

        return subject, body
