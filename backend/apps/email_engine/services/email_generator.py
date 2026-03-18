import os
import re
import time

import anthropic

from .documentation import build_documentation_checklist
from .guardrails import GuardrailChecker
from .prompts import APPROVAL_EMAIL_PROMPT, DENIAL_EMAIL_PROMPT


_INJECTION_BLOCKLIST = re.compile(
    r'(?:ignore\s+(?:previous|above|all)\s+instructions'
    r'|disregard\s+(?:previous|above|all)\s+instructions'
    r'|system\s+prompt'
    r'|you\s+are\s+now'
    r'|new\s+instructions'
    r'|forget\s+(?:previous|your|all)\s+instructions'
    r'|override\s+(?:previous|your|all)\s+instructions)',
    re.IGNORECASE,
)


def _sanitize_prompt_input(value, max_length=500):
    """Strip characters and patterns that could manipulate prompt structure."""
    if not isinstance(value, str):
        return value
    # Remove prompt injection characters
    value = re.sub(r'[<>\[\]{}]', '', value)
    # Collapse all whitespace (newlines, tabs) to single spaces
    value = re.sub(r'\s+', ' ', value)
    # Remove common prompt injection phrases
    value = _INJECTION_BLOCKLIST.sub('', value)
    return value[:max_length].strip()


class EmailGenerator:
    """Generates approval/denial emails via Claude with guardrail checks."""

    MAX_RETRIES = 3

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is not set')
        self.client = anthropic.Anthropic(api_key=api_key)
        self.guardrail_checker = GuardrailChecker()

    # Map ML feature names to plain-language lending criteria (Banking Code para 81)
    DENIAL_REASON_MAP = {
        'credit_score': 'Credit score below our lending threshold',
        'debt_to_income': 'Debt-to-income ratio above acceptable range',
        'employment_length': 'Employment tenure below minimum requirement',
        'annual_income': 'Income insufficient for requested loan amount',
        'loan_amount': 'Requested loan amount exceeds serviceable limit',
        'home_ownership': 'Property ownership status did not meet lending criteria',
        'loan_grade': 'Assessed risk grade outside lending policy',
        'loan_percent_income': 'Loan repayments would exceed serviceable share of income',
        'default_history': 'Previous default history on file',
        'num_open_accounts': 'Number of open credit accounts above policy threshold',
        'derogatory_records': 'Derogatory records present on credit file',
        'credit_utilization': 'Credit utilisation ratio above acceptable range',
        'total_accounts': 'Total credit account history below minimum requirement',
        'num_mortgages': 'Mortgage exposure above policy threshold',
        'revolving_balance': 'Revolving credit balance above acceptable range',
        'revolving_utilization': 'Revolving credit utilisation above acceptable range',
    }

    def _format_denial_reasons(self, feature_importances):
        """Convert ML feature importances to plain-language denial reasons."""
        if not feature_importances:
            return 'Credit assessment criteria not met'
        top_factors = sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)[:3]
        reasons = []
        for feature_name, _score in top_factors:
            readable = self.DENIAL_REASON_MAP.get(
                feature_name,
                feature_name.replace('_', ' ').capitalize() + ' outside acceptable range',
            )
            reasons.append(readable)
        return '; '.join(reasons)

    def generate(self, application, decision, attempt=1, confidence=None, profile_context=None):
        """Generate an approval/denial email for the given loan application."""
        # Reset retry state at the start of each generate() call
        self._last_feedback = ''

        start_time = time.time()

        applicant_name = _sanitize_prompt_input(
            f"{application.applicant.first_name} {application.applicant.last_name}".strip(),
            max_length=200,
        )
        if not applicant_name:
            applicant_name = _sanitize_prompt_input(application.applicant.username, max_length=200)

        context = {
            'applicant_name': applicant_name,
            'loan_amount': float(application.loan_amount),
            'purpose': application.get_purpose_display(),
            'decision': decision,
        }

        # Build banking context string from profile data
        banking_context = 'No banking relationship data available'
        if profile_context:
            lines = []
            if profile_context.get('account_tenure_years'):
                lines.append(f"- Account tenure: {profile_context['account_tenure_years']} years")
            if profile_context.get('loyalty_tier'):
                lines.append(f"- Loyalty tier: {profile_context['loyalty_tier']}")
            if profile_context.get('num_products'):
                lines.append(f"- Total banking products: {profile_context['num_products']}")
            if profile_context.get('on_time_payment_pct') is not None:
                lines.append(f"- On-time payment rate: {profile_context['on_time_payment_pct']:.1f}%")
            if profile_context.get('savings_balance') is not None:
                lines.append(f"- Savings balance: ${float(profile_context['savings_balance']):,.2f}")
            if profile_context.get('previous_loans_repaid'):
                lines.append(f"- Previous loans repaid: {profile_context['previous_loans_repaid']}")
            if profile_context.get('has_credit_card'):
                lines.append('- Existing credit card holder')
            if profile_context.get('has_mortgage'):
                lines.append('- Existing mortgage holder')
            banking_context = '\n'.join(lines) if lines else banking_context

        # Resolve confidence: prefer explicit param, then decision model, then 0.0
        if confidence is None:
            confidence = 0.0
            if hasattr(application, 'decision') and application.decision:
                confidence = application.decision.confidence

        # Build prompt
        if decision == 'approved':
            documentation_checklist = build_documentation_checklist(application)
            prompt = APPROVAL_EMAIL_PROMPT.format(
                applicant_name=applicant_name,
                loan_amount=float(application.loan_amount),
                purpose=application.get_purpose_display(),
                confidence=confidence,
                employment_type=application.get_employment_type_display(),
                applicant_type=application.get_applicant_type_display(),
                has_cosigner='Yes' if application.has_cosigner else 'No',
                has_hecs='Yes' if getattr(application, 'has_hecs', False) else 'No',
                documentation_checklist=documentation_checklist,
                banking_context=banking_context,
            )
        else:
            reasons = self._format_denial_reasons(
                application.decision.feature_importances
                if hasattr(application, 'decision') and application.decision
                else None
            )
            prompt = DENIAL_EMAIL_PROMPT.format(
                applicant_name=applicant_name,
                loan_amount=float(application.loan_amount),
                purpose=application.get_purpose_display(),
                reasons=reasons,
                banking_context=banking_context,
            )

        # Add retry feedback if not first attempt
        if attempt > 1:
            feedback = self._last_feedback
            prompt += f"\n\nIMPORTANT: Previous attempt failed guardrail checks: {feedback}. Please fix these issues and ensure compliance with all requirements."
            prompt += f"\n\n(This is generation attempt {attempt} of {self.MAX_RETRIES}.)"

        # Call Claude API
        from django.conf import settings as django_settings
        response = self.client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1024,
            temperature=getattr(django_settings, 'AI_TEMPERATURE_DECISION_EMAIL', 0.0),
            messages=[{'role': 'user', 'content': prompt}],
        )

        response_text = response.content[0].text
        generation_time = int((time.time() - start_time) * 1000)

        # Parse subject and body
        subject, body = self._parse_response(response_text)

        # Run guardrails (warning-severity checks provide retry feedback but do not block)
        guardrail_results = self.guardrail_checker.run_all_checks(body, context)
        all_passed = all(r['passed'] for r in guardrail_results if r.get('severity') != 'warning')

        # Retry if guardrails failed and we have attempts left
        if not all_passed and attempt < self.MAX_RETRIES:
            failed_checks = [r for r in guardrail_results if not r['passed']]
            self._last_feedback = "; ".join(f"{r['check_name']}: {r['details']}" for r in failed_checks)
            return self.generate(application, decision, attempt=attempt + 1, confidence=confidence, profile_context=profile_context)

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
