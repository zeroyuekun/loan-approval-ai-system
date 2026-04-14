import os
import re
import time

import anthropic
import httpx

from apps.ml_engine.services.reason_codes import REASON_CODE_MAP
from utils.sanitization import sanitize_prompt_input as _sanitize_prompt_input

from .documentation import build_documentation_checklist
from .guardrails import GuardrailChecker
from .pricing import calculate_loan_pricing
from .prompts import APPROVAL_EMAIL_PROMPT, DENIAL_EMAIL_PROMPT

EMAIL_SUBMIT_TOOL = {
    "name": "submit_email",
    "description": "Submit the generated email with subject and body.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Email subject line",
            },
            "body": {
                "type": "string",
                "description": "Complete email body text",
            },
        },
        "required": ["subject", "body"],
    },
}


class EmailGenerator:
    """Generates approval/denial emails via Claude with guardrail checks."""

    MAX_RETRIES = 3

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            self.client = anthropic.Anthropic(
                api_key=api_key,
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        else:
            self.client = None
        self.guardrail_checker = GuardrailChecker()
        self._consecutive_failures = 0
        self._circuit_open_until = 0

    # Map ML feature names to plain-language denial reasons
    DENIAL_REASON_MAP = {
        "credit_score": "Your credit score didn't meet the minimum we need for this loan",
        "debt_to_income": "You've got too much existing debt relative to your income for us to comfortably approve this",
        "employment_length": "You haven't been in your current role long enough for us to approve a loan of this size",
        "annual_income": "Your income doesn't quite support the loan amount you've asked for",
        "loan_amount": "The amount you've asked for is more than we can offer based on your current finances",
        "home_ownership": "Your current housing situation didn't meet our requirements for this loan type",
        "loan_grade": "Your overall financial profile fell outside what we can approve for this product",
        "loan_percent_income": "The repayments would take up too large a share of your income",
        "default_history": "There are previous defaults on your credit file that affected this decision",
        "num_open_accounts": "You've got too many open credit accounts for us to take on this loan right now",
        "derogatory_records": "There are some adverse entries on your credit file that we couldn't look past for this one",
        "credit_utilization": "You're using too much of your available credit at the moment",
        "total_accounts": "Your credit history isn't long enough for us to approve this loan",
        "num_mortgages": "You've already got too many mortgage commitments for us to add another",
        "revolving_balance": "Your credit card and revolving loan balances are too high right now",
        "revolving_utilization": "You're carrying too much on your revolving credit lines at the moment",
        # Stress testing & serviceability
        "rate_stress_buffer": "If interest rates were to rise, your finances may not comfortably handle the higher repayments",
        "stressed_repayment": "If interest rates go up, the repayments on this loan could become hard to manage",
        "stressed_dsr": "Your debt commitments would be too high to manage comfortably if interest rates rise",
        "stress_index": "Your financial position may not hold up well if economic conditions change",
        "hem_surplus": "After your living expenses, there isn't enough income left over to comfortably cover repayments",
        "uncommitted_monthly_income": "After your existing commitments, there isn't enough spare income each month to take on this loan",
        # Employment & stability
        "employment_stability": "Your employment history doesn't show enough stability for a loan of this size",
        "employment_type_payg_casual": "Casual employment doesn't meet what we need for this loan type",
        "employment_type_contract": "Contract employment doesn't meet what we need for this loan type",
        "employment_type_self_employed": "Your self-employment history isn't long enough for us to approve this loan",
        # Affordability
        "debt_service_coverage": "Based on your income and current commitments, the repayments would stretch your budget beyond what we're comfortable approving right now",
        "loan_to_income": "The loan amount is too large for your income to comfortably support",
        "serviceability_ratio": "Your income can't comfortably cover the total repayments needed for this loan",
        "expense_to_income": "Your living expenses are too high relative to your income for us to approve this",
        "monthly_repayment_ratio": "The monthly repayments would eat up too much of your income",
        "net_monthly_surplus": "After all your expenses and debts, there isn't enough left over each month to take this on",
        # Credit bureau
        "bureau_risk_score": "Your credit bureau score didn't meet the minimum we need for this loan",
        "credit_utilization_pct": "You're using too much of your available credit at the moment",
        "num_credit_enquiries_6m": "There have been too many credit enquiries on your file recently",
        # Loan structure
        "lvr": "The deposit isn't large enough relative to the property value for this loan",
        "deposit_ratio": "Your deposit is too small for what you're looking to borrow",
        "savings_to_loan_ratio": "Your savings are too low relative to the loan amount you've requested",
        # Combined factors
        "lvr_x_dti": "The combination of your deposit size and existing debt levels falls outside our lending criteria for this product",
        "lvr_x_property_growth": "Given the deposit amount relative to the property value and the growth outlook for the area, this loan doesn't meet our risk settings at the moment",
        "credit_score_x_tenure": "Your credit history combined with your time in your current role doesn't quite meet what we need for this product",
        "deposit_x_income_stability": "Your deposit size and income stability together don't meet our lending requirements right now",
        "dti_x_rate_sensitivity": "Your existing debt level means repayments could become difficult if interest rates were to rise",
        "credit_x_employment": "Your credit history and employment type together don't meet our criteria for this product",
        # CCR / payment history
        "num_late_payments_24m": "You've had late payments on your credit accounts in the last 24 months",
        "worst_late_payment_days": "You've had overdue payments on your credit file that exceeded our acceptable threshold",
        # Bureau / behavioural
        "num_defaults_5yr": "There are default records on your credit file from the past five years",
        "num_hardship_flags": "There are financial hardship indicators on your credit file",
        "num_dishonours_12m": "There have been dishonoured transactions on your accounts in the last 12 months",
        "gambling_transaction_flag": "Gambling transactions were detected in your account history",
        "days_negative_balance_90d": "Your account has been in negative balance too frequently in recent months",
        "bnpl_monthly_commitment": "Your buy-now-pay-later commitments reduce the amount we can lend",
    }

    # Map feature names to positive-frame phrases for approved-loan emails.
    # Qualitative only — never promise a number or certainty.
    APPROVAL_FACTOR_MAP = {
        "credit_score": "strong credit history",
        "employment_length": "stable employment history",
        "employment_stability": "consistent employment",
        "annual_income": "strong income",
        "debt_to_income": "a manageable debt-to-income position",
        "loan_to_income": "a loan amount well matched to your income",
        "home_ownership": "a stable housing situation",
        "savings_balance": "healthy savings",
        "savings_to_loan_ratio": "a strong savings buffer",
        "num_late_payments_24m": "a clean recent repayment record",
        "worst_late_payment_days": "no material late payments on your credit file",
        "credit_utilization_pct": "low credit utilisation",
        "num_credit_enquiries_6m": "a light recent credit enquiry footprint",
        "uncommitted_monthly_income": "a comfortable monthly surplus after expenses",
        "net_monthly_surplus": "a comfortable monthly surplus after expenses",
        "serviceability_ratio": "strong serviceability",
        "has_cosigner": "co-signer support on this application",
    }

    _POLICY_REASON_CODE_RE = re.compile(r"\[(R\d{2,3})\]")

    def _format_denial_reasons(self, feature_importances, shap_values=None, reasoning=None):
        """Convert per-applicant SHAP values to plain-language denial reasons.

        Preference order:
        1. Policy-gate reason code in `reasoning` (e.g. "[R71] ...") — used when a
           deterministic rule denied the application before the ML model ran, so no
           SHAP values exist.
        2. SHAP values (per-applicant, explains why THIS person was denied).
        3. Global feature importances (model-wide weights, same for everyone).
        """
        if reasoning and isinstance(reasoning, str):
            match = self._POLICY_REASON_CODE_RE.search(reasoning)
            if match:
                code = match.group(1)
                for _, (mapped_code, text) in REASON_CODE_MAP.items():
                    if mapped_code == code:
                        return text

        if not feature_importances and not shap_values:
            return "Credit assessment criteria not met"

        if shap_values:
            # Use negative SHAP values — these are the features that pushed
            # this specific applicant toward denial
            negative_shap = {k: abs(v) for k, v in shap_values.items() if v < 0}
            if negative_shap:
                top_factors = sorted(negative_shap.items(), key=lambda x: x[1], reverse=True)[:3]
            else:
                top_factors = sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)[:3]
        else:
            top_factors = sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)[:3]

        reasons = []
        for feature_name, _score in top_factors:
            readable = self.DENIAL_REASON_MAP.get(
                feature_name,
                "Part of your financial profile didn't meet our lending criteria",
            )
            reasons.append(readable)
        return "; ".join(reasons)

    def _format_approval_factors(self, feature_importances=None, shap_values=None, top_n: int = 3) -> str:
        """Build a qualitative factor string for approval emails.

        Picks features that supported approval (positive SHAP contribution) and
        maps them to reviewer-approved positive phrases. Falls back to
        feature_importances only if SHAP is absent. Returns an empty string when
        no signal is available — the prompt is instructed to omit the sentence.
        """
        if shap_values:
            positive = {k: v for k, v in shap_values.items() if isinstance(v, (int, float)) and v > 0}
            if positive:
                ranked = sorted(positive.items(), key=lambda x: x[1], reverse=True)[:top_n]
            elif feature_importances:
                ranked = sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)[:top_n]
            else:
                return ""
        elif feature_importances:
            ranked = sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)[:top_n]
        else:
            return ""

        phrases = []
        for feature_name, _ in ranked:
            phrase = self.APPROVAL_FACTOR_MAP.get(feature_name, "an aspect of your financial profile")
            if phrase not in phrases:
                phrases.append(phrase)
        return ", ".join(phrases)

    def generate(self, application, decision, attempt=1, confidence=None, profile_context=None):
        """Generate an approval/denial email for the given loan application."""
        # Reset retry state only on the first attempt (not recursive retries)
        if attempt == 1:
            self._last_feedback = ""

        start_time = time.time()

        applicant_name = _sanitize_prompt_input(
            f"{application.applicant.first_name} {application.applicant.last_name}".strip(),
            max_length=200,
        )
        if not applicant_name:
            applicant_name = _sanitize_prompt_input(application.applicant.username, max_length=200)

        context = {
            "applicant_name": applicant_name,
            "loan_amount": float(application.loan_amount),
            "purpose": application.get_purpose_display(),
            "decision": decision,
        }

        # Build banking context string from profile data
        # Sanitize all string values to prevent prompt injection
        banking_context = "No banking relationship data available"
        if profile_context:
            lines = []
            if profile_context.get("account_tenure_years"):
                lines.append(
                    f"- Account tenure: {_sanitize_prompt_input(str(profile_context['account_tenure_years']), max_length=50)} years"
                )
            if profile_context.get("loyalty_tier"):
                lines.append(
                    f"- Loyalty tier: {_sanitize_prompt_input(str(profile_context['loyalty_tier']), max_length=100)}"
                )
            if profile_context.get("num_products"):
                lines.append(
                    f"- Total banking products: {_sanitize_prompt_input(str(profile_context['num_products']), max_length=50)}"
                )
            if profile_context.get("on_time_payment_pct") is not None:
                lines.append(f"- On-time payment rate: {float(profile_context['on_time_payment_pct']):.1f}%")
            if profile_context.get("savings_balance") is not None:
                lines.append(f"- Savings balance: ${float(profile_context['savings_balance']):,.2f}")
            if profile_context.get("previous_loans_repaid"):
                lines.append(
                    f"- Previous loans repaid: {_sanitize_prompt_input(str(profile_context['previous_loans_repaid']), max_length=50)}"
                )
            if profile_context.get("has_credit_card"):
                lines.append("- Existing credit card holder")
            if profile_context.get("has_mortgage"):
                lines.append("- Existing mortgage holder")
            banking_context = "\n".join(lines) if lines else banking_context

        # Resolve confidence: prefer explicit param, then decision model, then 0.0
        if confidence is None:
            confidence = 0.0
            if hasattr(application, "decision") and application.decision:
                confidence = application.decision.confidence

        # Build prompt
        if decision == "approved":
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

            decision_obj = getattr(application, "decision", None)
            approval_factors = self._format_approval_factors(
                feature_importances=decision_obj.feature_importances if decision_obj else None,
                shap_values=decision_obj.shap_values if decision_obj else None,
            )

            prompt = APPROVAL_EMAIL_PROMPT.format(
                applicant_name=applicant_name,
                loan_amount=float(application.loan_amount),
                purpose=application.get_purpose_display(),
                confidence=confidence,
                employment_type=application.get_employment_type_display(),
                applicant_type=application.get_applicant_type_display(),
                has_cosigner="Yes" if application.has_cosigner else "No",
                has_hecs="Yes" if getattr(application, "has_hecs", False) else "No",
                documentation_checklist=documentation_checklist,
                banking_context=banking_context,
                approval_factors=approval_factors,
            )
            # Append pricing context after the main prompt
            prompt += f"\n\n{pricing_context}"

            # Store pricing in context for guardrail validation
            context["pricing"] = pricing
        else:
            decision_obj = getattr(application, "decision", None)
            reasons = self._format_denial_reasons(
                decision_obj.feature_importances if decision_obj else None,
                shap_values=decision_obj.shap_values if decision_obj else None,
                reasoning=decision_obj.reasoning if decision_obj else None,
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
                    "\nThis is your FINAL attempt. If guardrails fail again, the email "
                    "will be escalated to human review. Be conservative: when in doubt, "
                    "use simpler language and stick to the exact template structure.\n"
                )

        # Check circuit breaker — fallback to template if API is down
        if self._consecutive_failures >= 3 and time.time() < self._circuit_open_until:
            return self._generate_fallback(application, decision, context, start_time)

        # Pre-flight: detect billing/auth errors immediately so the pipeline
        # completes end-to-end using templates rather than failing at this step.
        if attempt == 1 and not self._api_available():
            return self._generate_fallback(application, decision, context, start_time)

        # Call Claude API with tool_use for structured output (with budget check)
        from django.conf import settings as django_settings

        from apps.agents.services.api_budget import ApiBudgetGuard, BudgetExhausted, guarded_api_call

        budget = ApiBudgetGuard()
        try:
            budget.check_budget()
        except BudgetExhausted:
            return self._generate_fallback(application, decision, context, start_time)

        # Approval emails are much longer (loan details, next steps, documentation,
        # before-you-sign, hardship, attachments, comparison rate footnote, AFCA).
        # 1024 tokens truncates the tool_use JSON, producing an empty body.
        token_limit = 4096 if decision == "approved" else 2048

        input_tokens = 0
        output_tokens = 0
        try:
            # Retry with exponential backoff on rate limit (429) errors.
            # The org-level limit is 30k input tokens/min — with prompts
            # ~5k tokens each, rapid sequential calls will hit this.
            max_api_retries = 3
            response = None
            _model = "claude-sonnet-4-20250514"
            for api_attempt in range(max_api_retries):
                try:
                    response = guarded_api_call(
                        self.client,
                        model=_model,
                        max_tokens=token_limit,
                        temperature=getattr(django_settings, "AI_TEMPERATURE_DECISION_EMAIL", 0.0),
                        messages=[{"role": "user", "content": prompt}],
                        tools=[EMAIL_SUBMIT_TOOL],
                        tool_choice={"type": "tool", "name": "submit_email"},
                    )
                    break  # Success — exit retry loop
                except BudgetExhausted:
                    return self._generate_fallback(application, decision, context, start_time)
                except anthropic.RateLimitError:
                    if api_attempt < max_api_retries - 1:
                        wait = 2**api_attempt * 30  # 30s, 60s, 120s
                        import logging

                        logging.getLogger(__name__).warning(
                            "Rate limited (429), retrying in %ds (attempt %d/%d)",
                            wait,
                            api_attempt + 1,
                            max_api_retries,
                        )
                        time.sleep(wait)
                    else:
                        raise  # Final attempt — propagate to outer handler

            self._consecutive_failures = 0
            # Read actual token usage from the response
            usage = getattr(response, "usage", None)
            if usage:
                input_tokens = getattr(usage, "input_tokens", 0)
                output_tokens = getattr(usage, "output_tokens", 0)
        except BudgetExhausted:
            return self._generate_fallback(application, decision, context, start_time)
        except Exception:
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
        all_passed = all(r["passed"] for r in guardrail_results if r.get("severity") != "warning")

        # Retry if guardrails failed and we have attempts left.
        # Structured feedback tells Claude exactly what to fix.
        if not all_passed and attempt < self.MAX_RETRIES:
            failed_checks = [r for r in guardrail_results if not r["passed"]]
            # Group failures by severity for clearer feedback
            critical = [r for r in failed_checks if r.get("weight", 0) >= 15]
            moderate = [r for r in failed_checks if 5 <= r.get("weight", 0) < 15]
            minor = [r for r in failed_checks if r.get("weight", 0) < 5]

            feedback_parts = []
            if critical:
                feedback_parts.append(
                    "CRITICAL (must fix): " + "; ".join(f"{r['check_name']}: {r['details']}" for r in critical)
                )
            if moderate:
                feedback_parts.append(
                    "MODERATE (should fix): " + "; ".join(f"{r['check_name']}: {r['details']}" for r in moderate)
                )
            if minor:
                feedback_parts.append(
                    "MINOR (nice to fix): " + "; ".join(f"{r['check_name']}: {r['details']}" for r in minor)
                )
            self._last_feedback = "\n".join(feedback_parts)
            return self.generate(
                application, decision, attempt=attempt + 1, confidence=confidence, profile_context=profile_context
            )

        return {
            "subject": subject,
            "body": body,
            "prompt_used": prompt,
            "guardrail_results": guardrail_results,
            "passed_guardrails": all_passed,
            "quality_score": quality_score,
            "generation_time_ms": generation_time,
            "attempt_number": attempt,
            "template_fallback": False,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    def _parse_tool_response(self, response):
        """Extract subject and body from tool_use structured response."""
        import logging

        logger = logging.getLogger("email_engine.generator")

        # Detect truncation: stop_reason == 'max_tokens' means the response
        # was cut off and the tool_use JSON is likely incomplete/empty.
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            logger.warning(
                "Claude response truncated (stop_reason=max_tokens) — max_tokens too low for this email template"
            )

        try:
            tool_block = next(b for b in response.content if b.type == "tool_use")
            subject = tool_block.input.get("subject", "").strip()
            body = tool_block.input.get("body", "").strip()
            if subject and body:
                return subject, body
            # Tool block found but body is empty — likely truncated
            if subject and not body:
                logger.warning(
                    "Tool response has subject but empty body (stop_reason=%s) — falling back to text parse",
                    stop_reason,
                )
        except (StopIteration, AttributeError) as exc:
            logger.debug(
                "tool_block_missing_falling_back_to_text",
                extra={"error": type(exc).__name__, "stop_reason": stop_reason},
            )

        # Fallback: try to parse from text block (in case tool_use wasn't used)
        text_block = next((b for b in response.content if b.type == "text"), None)
        if text_block:
            return self._parse_text_response(text_block.text)

        return "Regarding Your Loan Application", ""

    def _parse_text_response(self, text):
        """Legacy parser for free-form text responses."""
        lines = text.strip().split("\n")
        subject = ""
        body_start = 0

        for i, line in enumerate(lines):
            if line.lower().startswith("subject:"):
                subject = line[len("Subject:") :].strip()
                body_start = i + 1
                break

        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1

        body = "\n".join(lines[body_start:]).strip()

        if not subject:
            subject = "Regarding Your Loan Application"

        return subject, body

    def _api_available(self):
        """Quick check if the Claude API is reachable and has credits.

        Sends a minimal 1-token request. Returns False on billing, auth,
        or connection errors so the caller can fall back to templates.
        """
        import logging

        logger = logging.getLogger("email_engine.generator")
        if self.client is None:
            logger.info("No API client configured — using template fallback")
            return False
        try:
            self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except anthropic.AuthenticationError:
            logger.warning("Claude API auth failed — using template fallback")
            return False
        except anthropic.BadRequestError as e:
            if "credit" in str(e).lower() or "balance" in str(e).lower():
                logger.warning("Claude API credit insufficient — using template fallback")
                return False
            return True  # other bad request errors may be prompt-specific
        except (anthropic.APIConnectionError, anthropic.APITimeoutError):
            logger.warning("Claude API unreachable — using template fallback")
            return False
        except Exception:
            return True  # let the main flow handle unexpected errors

    def _generate_fallback(self, application, decision, context, start_time):
        """Generate email from smart template when Claude API is unavailable.

        Fills in applicant-specific details: pricing, denial reasons, conditions,
        employment context, and tailored guidance.
        """
        from .pricing import calculate_loan_pricing
        from .template_fallback import generate_approval_template, generate_denial_template

        applicant_name = (
            _sanitize_prompt_input(
                f"{application.applicant.first_name} {application.applicant.last_name}".strip(),
                max_length=200,
            )
            or application.applicant.username
        )

        pricing = None
        if decision == "approved":
            # Calculate real pricing even in fallback mode
            pricing = context.get("pricing")
            if not pricing:
                try:
                    pricing = calculate_loan_pricing(application)
                except Exception:
                    pricing = None

            decision_obj_fb = getattr(application, "decision", None)
            approval_factors_fb = self._format_approval_factors(
                feature_importances=decision_obj_fb.feature_importances if decision_obj_fb else None,
                shap_values=decision_obj_fb.shap_values if decision_obj_fb else None,
            )
            result = generate_approval_template(
                applicant_name,
                float(application.loan_amount),
                application.get_purpose_display(),
                pricing=pricing,
                employment_type=application.get_employment_type_display(),
                applicant_type=application.get_applicant_type_display(),
                has_cosigner=application.has_cosigner,
                approval_factors=approval_factors_fb,
            )
        else:
            # Gather rich denial context
            feature_importances = None
            shap_values = None
            reasoning = None
            if hasattr(application, "decision") and application.decision:
                feature_importances = application.decision.feature_importances
                shap_values = application.decision.shap_values
                reasoning = application.decision.reasoning

            denial_reasons = self._format_denial_reasons(
                feature_importances, shap_values=shap_values, reasoning=reasoning
            )

            credit_score = getattr(application, "credit_score", None)
            debt_to_income = getattr(application, "debt_to_income", None)

            result = generate_denial_template(
                applicant_name,
                float(application.loan_amount),
                application.get_purpose_display(),
                denial_reasons=denial_reasons,
                feature_importances=feature_importances,
                credit_score=int(credit_score) if credit_score else None,
                debt_to_income=float(debt_to_income) if debt_to_income else None,
                employment_type=application.get_employment_type_display(),
            )

        generation_time = int((time.time() - start_time) * 1000)

        # Ensure pricing is in context for guardrail validation
        # (the main generate() path adds pricing to context at line 176,
        # but the pre-flight fallback path skips that)
        if "pricing" not in context and decision == "approved" and pricing:
            context["pricing"] = pricing

        # Run full guardrails on template emails — templates are designed
        # to pass all 18 checks including hallucinated numbers and required elements.
        guardrail_results = self.guardrail_checker.run_all_checks(
            result["body"],
            context,
        )
        all_passed = all(r["passed"] for r in guardrail_results if r.get("severity") != "warning")

        return {
            "subject": result["subject"],
            "body": result["body"],
            "prompt_used": "[TEMPLATE FALLBACK — Claude API unavailable]",
            "guardrail_results": guardrail_results,
            "passed_guardrails": all_passed,
            "quality_score": self.guardrail_checker.compute_quality_score(guardrail_results),
            "generation_time_ms": generation_time,
            "attempt_number": 1,
            "template_fallback": True,
            "input_tokens": 0,
            "output_tokens": 0,
        }
