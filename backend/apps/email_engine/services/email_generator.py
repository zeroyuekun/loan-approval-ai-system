import os
import re
import time

import anthropic
import httpx

from utils.sanitization import sanitize_prompt_input as _sanitize_prompt_input

from .documentation import build_documentation_checklist
from .guardrails import GuardrailChecker
from .pricing import calculate_loan_pricing
from .prompts import APPROVAL_EMAIL_PROMPT, DENIAL_EMAIL_PROMPT


EMAIL_SUBMIT_TOOL = {
    'name': 'submit_email',
    'description': 'Submit the generated email with subject and body.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'subject': {
                'type': 'string',
                'description': 'Email subject line',
            },
            'body': {
                'type': 'string',
                'description': 'Complete email body text',
            },
        },
        'required': ['subject', 'body'],
    },
}


class EmailGenerator:
    """Generates approval/denial emails via Claude with guardrail checks."""

    MAX_RETRIES = 3

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is not set')
        self.client = anthropic.Anthropic(
            api_key=api_key,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        self.guardrail_checker = GuardrailChecker()
        self._consecutive_failures = 0
        self._circuit_open_until = 0

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
        # Sanitize all string values to prevent prompt injection
        banking_context = 'No banking relationship data available'
        if profile_context:
            lines = []
            if profile_context.get('account_tenure_years'):
                lines.append(f"- Account tenure: {_sanitize_prompt_input(str(profile_context['account_tenure_years']), max_length=50)} years")
            if profile_context.get('loyalty_tier'):
                lines.append(f"- Loyalty tier: {_sanitize_prompt_input(str(profile_context['loyalty_tier']), max_length=100)}")
            if profile_context.get('num_products'):
                lines.append(f"- Total banking products: {_sanitize_prompt_input(str(profile_context['num_products']), max_length=50)}")
            if profile_context.get('on_time_payment_pct') is not None:
                lines.append(f"- On-time payment rate: {float(profile_context['on_time_payment_pct']):.1f}%")
            if profile_context.get('savings_balance') is not None:
                lines.append(f"- Savings balance: ${float(profile_context['savings_balance']):,.2f}")
            if profile_context.get('previous_loans_repaid'):
                lines.append(f"- Previous loans repaid: {_sanitize_prompt_input(str(profile_context['previous_loans_repaid']), max_length=50)}")
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

            # Calculate real pricing for the loan
            pricing = calculate_loan_pricing(application)
            pricing_context = (
                f"=== LOAN PRICING (use these EXACT figures in the email) ===\n"
                f"Interest Rate: {pricing['interest_rate']} ({pricing['rate_type']})\n"
                f"Comparison Rate: {pricing['comparison_rate']}*\n"
                f"Loan Term: {pricing['loan_term_display']}\n"
                f"Estimated Monthly Payment: {pricing['monthly_payment']}\n"
                f"Establishment Fee: {pricing['establishment_fee']}\n"
                f"First Repayment Date: {pricing['first_repayment_date']}\n"
                f"Sign-by Date: {pricing['sign_by_date']}\n"
                f"Comparison Rate Benchmark: {pricing['comparison_benchmark']}\n"
                f"\n"
                f"IMPORTANT: Use these exact numbers in the email. Do NOT use placeholders "
                f"like [X.XX] for any of the above values. These have been calculated by "
                f"our product pricing engine based on the applicant's credit profile."
            )

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
            # Append pricing context after the main prompt
            prompt += f"\n\n{pricing_context}"

            # Store pricing in context for guardrail validation
            context['pricing'] = pricing
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

        # Add retry feedback if not first attempt.
        # The feedback is structured to tell Claude exactly what failed,
        # why it failed, and what the correct fix looks like. This
        # graduated approach produces better corrections than just
        # restating the error.
        if attempt > 1:
            feedback = self._last_feedback
            prompt += (
                f"\n\n=== RETRY FEEDBACK (Attempt {attempt}/{self.MAX_RETRIES}) ===\n"
                f"Your previous email FAILED the following compliance checks:\n\n"
                f"{feedback}\n\n"
                f"RULES FOR THIS RETRY:\n"
                f"1. Fix ONLY the issues listed above. Do not change parts that were correct.\n"
                f"2. If a check flagged a specific phrase, remove or replace that exact phrase.\n"
                f"3. If a required element is missing, add it in the correct section.\n"
                f"4. If a number was hallucinated, use ONLY the figures provided in the pricing section.\n"
                f"5. Do not add apologies about the retry or mention that this is a corrected version.\n"
                f"6. Maintain the same overall structure and tone — just fix the flagged issues.\n"
            )
            if attempt == self.MAX_RETRIES:
                prompt += (
                    f"\nThis is your FINAL attempt. If guardrails fail again, the email "
                    f"will be escalated to human review. Be conservative: when in doubt, "
                    f"use simpler language and stick to the exact template structure.\n"
                )

        # Check circuit breaker — fallback to template if API is down
        if self._consecutive_failures >= 3 and time.time() < self._circuit_open_until:
            return self._generate_fallback(application, decision, context, start_time)

        # Call Claude API with tool_use for structured output (with budget check)
        from django.conf import settings as django_settings
        from apps.agents.services.api_budget import ApiBudgetGuard
        budget = ApiBudgetGuard()
        budget.check_budget()

        input_tokens = 0
        output_tokens = 0
        try:
            response = self.client.messages.create(
                model='claude-sonnet-4-20250514',
                max_tokens=1024,
                temperature=getattr(django_settings, 'AI_TEMPERATURE_DECISION_EMAIL', 0.0),
                messages=[{'role': 'user', 'content': prompt}],
                tools=[EMAIL_SUBMIT_TOOL],
                tool_choice={'type': 'tool', 'name': 'submit_email'},
            )

            # Track budget usage
            usage = getattr(response, 'usage', None)
            if usage:
                input_tokens = getattr(usage, 'input_tokens', 0)
                output_tokens = getattr(usage, 'output_tokens', 0)
                budget.record_call(input_tokens=input_tokens, output_tokens=output_tokens)
            budget.record_success()
            self._consecutive_failures = 0
        except Exception as e:
            budget.record_failure()
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._circuit_open_until = time.time() + 600  # 10 min cooldown
            raise

        # Extract structured output from tool_use response
        subject, body = self._parse_tool_response(response)
        generation_time = int((time.time() - start_time) * 1000)

        # Run guardrails (warning-severity checks provide retry feedback but do not block)
        guardrail_results = self.guardrail_checker.run_all_checks(body, context)
        quality_score = self.guardrail_checker.compute_quality_score(guardrail_results)
        all_passed = all(r['passed'] for r in guardrail_results if r.get('severity') != 'warning')

        # Retry if guardrails failed and we have attempts left.
        # Structured feedback tells Claude exactly what to fix.
        if not all_passed and attempt < self.MAX_RETRIES:
            failed_checks = [r for r in guardrail_results if not r['passed']]
            # Group failures by severity for clearer feedback
            critical = [r for r in failed_checks if r.get('weight', 0) >= 15]
            moderate = [r for r in failed_checks if 5 <= r.get('weight', 0) < 15]
            minor = [r for r in failed_checks if r.get('weight', 0) < 5]

            feedback_parts = []
            if critical:
                feedback_parts.append(
                    "CRITICAL (must fix): " +
                    "; ".join(f"{r['check_name']}: {r['details']}" for r in critical)
                )
            if moderate:
                feedback_parts.append(
                    "MODERATE (should fix): " +
                    "; ".join(f"{r['check_name']}: {r['details']}" for r in moderate)
                )
            if minor:
                feedback_parts.append(
                    "MINOR (nice to fix): " +
                    "; ".join(f"{r['check_name']}: {r['details']}" for r in minor)
                )
            self._last_feedback = "\n".join(feedback_parts)
            return self.generate(application, decision, attempt=attempt + 1, confidence=confidence, profile_context=profile_context)

        return {
            'subject': subject,
            'body': body,
            'prompt_used': prompt,
            'guardrail_results': guardrail_results,
            'passed_guardrails': all_passed,
            'quality_score': quality_score,
            'generation_time_ms': generation_time,
            'attempt_number': attempt,
            'template_fallback': False,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
        }

    def _parse_tool_response(self, response):
        """Extract subject and body from tool_use structured response."""
        try:
            tool_block = next(b for b in response.content if b.type == 'tool_use')
            subject = tool_block.input.get('subject', '').strip()
            body = tool_block.input.get('body', '').strip()
            if subject and body:
                return subject, body
        except (StopIteration, AttributeError):
            pass

        # Fallback: try to parse from text block (in case tool_use wasn't used)
        text_block = next((b for b in response.content if b.type == 'text'), None)
        if text_block:
            return self._parse_text_response(text_block.text)

        return 'Regarding Your Loan Application', ''

    def _parse_text_response(self, text):
        """Legacy parser for free-form text responses."""
        lines = text.strip().split('\n')
        subject = ''
        body_start = 0

        for i, line in enumerate(lines):
            if line.lower().startswith('subject:'):
                subject = line[len('Subject:'):].strip()
                body_start = i + 1
                break

        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1

        body = '\n'.join(lines[body_start:]).strip()

        if not subject:
            subject = 'Regarding Your Loan Application'

        return subject, body

    def _generate_fallback(self, application, decision, context, start_time):
        """Generate email from static template when Claude API is unavailable."""
        from .template_fallback import generate_approval_template, generate_denial_template

        applicant_name = _sanitize_prompt_input(
            f"{application.applicant.first_name} {application.applicant.last_name}".strip(),
            max_length=200,
        ) or application.applicant.username

        if decision == 'approved':
            result = generate_approval_template(
                applicant_name,
                float(application.loan_amount),
                application.get_purpose_display(),
                pricing=context.get('pricing'),
            )
        else:
            denial_reasons = self._format_denial_reasons(
                application.decision.feature_importances
                if hasattr(application, 'decision') and application.decision
                else None
            )
            result = generate_denial_template(
                applicant_name,
                float(application.loan_amount),
                application.get_purpose_display(),
                denial_reasons=denial_reasons,
            )

        generation_time = int((time.time() - start_time) * 1000)

        # Run guardrails on template output too
        guardrail_results = self.guardrail_checker.run_all_checks(result['body'], context)
        all_passed = all(r['passed'] for r in guardrail_results if r.get('severity') != 'warning')

        return {
            'subject': result['subject'],
            'body': result['body'],
            'prompt_used': '[TEMPLATE FALLBACK — Claude API unavailable]',
            'guardrail_results': guardrail_results,
            'passed_guardrails': all_passed,
            'quality_score': self.guardrail_checker.compute_quality_score(guardrail_results),
            'generation_time_ms': generation_time,
            'attempt_number': 1,
            'template_fallback': True,
            'input_tokens': 0,
            'output_tokens': 0,
        }
