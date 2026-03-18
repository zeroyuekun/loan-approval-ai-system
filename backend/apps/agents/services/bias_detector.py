import json
import logging
import os
import re

import anthropic
from django.conf import settings as django_settings

from .deterministic_prescreen import DeterministicBiasPreScreen

logger = logging.getLogger('agents.bias_detector')


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
    value = re.sub(r'[<>\[\]{}]', '', value)
    value = re.sub(r'\s+', ' ', value)
    value = _INJECTION_BLOCKLIST.sub('', value)
    return value[:max_length].strip()


def _parse_json_response(response_text, fallback):
    """Extract JSON from a response, returning fallback on failure."""
    try:
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        return json.loads(response_text[json_start:json_end])
    except (json.JSONDecodeError, ValueError):
        return fallback


def _extract_tool_result(response, fallback):
    """Extract structured result from tool_use response, with fallback."""
    try:
        tool_block = next(b for b in response.content if b.type == 'tool_use')
        return tool_block.input
    except (StopIteration, AttributeError):
        text_block = next((b for b in response.content if b.type == 'text'), None)
        if text_block:
            return _parse_json_response(text_block.text, fallback)
        return fallback


# ---------------------------------------------------------------------------
# Tool definitions for structured output via tool_use
# ---------------------------------------------------------------------------

BIAS_ANALYSIS_TOOL = {
    'name': 'record_bias_analysis',
    'description': 'Record the bias analysis results for this email.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
            'categories': {
                'type': 'array',
                'items': {
                    'type': 'string',
                    'enum': ['gender', 'race', 'age', 'religion', 'disability', 'marital_status'],
                },
            },
            'analysis': {'type': 'string'},
        },
        'required': ['score', 'categories', 'analysis'],
    },
}

EMAIL_REVIEW_TOOL = {
    'name': 'record_review_decision',
    'description': 'Record the senior compliance review decision.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'approved': {'type': 'boolean'},
            'confidence': {'type': 'number', 'minimum': 0.0, 'maximum': 1.0},
            'reasoning': {'type': 'string'},
        },
        'required': ['approved', 'confidence', 'reasoning'],
    },
}

MARKETING_BIAS_TOOL = {
    'name': 'record_marketing_bias_analysis',
    'description': 'Record the marketing email bias analysis results.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
            'categories': {
                'type': 'array',
                'items': {
                    'type': 'string',
                    'enum': [
                        'patronising_tone', 'pressure_tactics',
                        'discriminatory_product_steering', 'false_promises',
                        'gender', 'race', 'age', 'religion', 'disability', 'marital_status',
                    ],
                },
            },
            'analysis': {'type': 'string'},
        },
        'required': ['score', 'categories', 'analysis'],
    },
}

MARKETING_REVIEW_TOOL = {
    'name': 'record_marketing_review_decision',
    'description': 'Record the senior compliance review decision for marketing email.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'approved': {'type': 'boolean'},
            'confidence': {'type': 'number', 'minimum': 0.0, 'maximum': 1.0},
            'reasoning': {'type': 'string'},
        },
        'required': ['approved', 'confidence', 'reasoning'],
    },
}


# ---------------------------------------------------------------------------
# Agent 1: Compliance Analyst — first-pass bias detection on decision emails
# ---------------------------------------------------------------------------

class BiasDetector:
    """Junior compliance analyst that screens loan decision emails for bias.

    Role: You are a methodical compliance analyst at an Australian bank. You have
    been on the team for two years. You follow the checklist. You reference the
    legislation by section number. You do not editorialize — you score and cite.
    If something is clean, you say so and move on. If something is borderline,
    you flag it for your senior to review. You never let something slide because
    "it's probably fine."
    """

    BIAS_CATEGORIES = ['gender', 'race', 'age', 'religion', 'disability', 'marital_status']

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is not set')
        self.client = anthropic.Anthropic(api_key=api_key)
        self.prescreener = DeterministicBiasPreScreen()

    def analyze(self, email_text, application_context):
        """Score email text for bias (0-100) using deterministic-first approach.

        How real Australian banks (CBA, Westpac, ANZ, NAB) handle compliance on
        outbound lending communications:

        1. Run a deterministic compliance checklist (prohibited language, tone,
           required elements). This is the primary gate — binary pass/fail.
        2. If the checklist passes, the email ships. No further scoring needed.
        3. LLM analysis is only invoked when the deterministic system flags
           something that needs human-level interpretation (e.g., a prohibited
           term found in ambiguous context like a legal disclosure).
        4. Human escalation is reserved for confirmed high-severity violations,
           not borderline scores.

        This mirrors APRA's CPG 235 (Managing Data Risk) principle: use
        deterministic controls as the primary gate, with model-based checks
        as a secondary layer only where deterministic rules are insufficient.
        """
        prescreen = self.prescreener.prescreen_decision_email(email_text, application_context)
        det_score = prescreen['deterministic_score']

        bias_threshold_pass = getattr(django_settings, 'BIAS_THRESHOLD_PASS', 60)
        bias_threshold_review = getattr(django_settings, 'BIAS_THRESHOLD_REVIEW', 80)

        # ── Clean email: all deterministic checks passed ──
        # Real banks don't ask a second reviewer to "score" a clean email.
        # If the compliance checklist passes, the email ships.
        if prescreen['all_clean']:
            logger.info('Bias pre-screen: all checks passed, deterministic_score=%d — email compliant', det_score)
            return {
                'score': det_score,
                'deterministic_score': det_score,
                'llm_raw_score': None,
                'score_source': 'deterministic',
                'categories': [],
                'analysis': 'All deterministic compliance checks passed. No bias detected.',
                'flagged': False,
                'requires_human_review': False,
            }

        # ── Severe violation: prohibited language or multiple failures ──
        # Clear compliance breach — no need for LLM interpretation.
        if det_score > bias_threshold_review:
            logger.warning('Bias pre-screen: severe violation, deterministic_score=%d — blocking', det_score)
            return {
                'score': det_score,
                'deterministic_score': det_score,
                'llm_raw_score': None,
                'score_source': 'deterministic',
                'categories': [f['check_name'] for f in prescreen['findings']],
                'analysis': '; '.join(f['details'] for f in prescreen['findings']),
                'flagged': True,
                'requires_human_review': True,
            }

        # ── Minor findings (e.g., AI giveaway language, tone) ──
        # Score is low-to-moderate. These are style issues, not bias.
        # Real banks handle these by regenerating the email, not escalating.
        if det_score <= bias_threshold_pass:
            logger.info('Bias pre-screen: minor findings only, deterministic_score=%d — compliant', det_score)
            return {
                'score': det_score,
                'deterministic_score': det_score,
                'llm_raw_score': None,
                'score_source': 'deterministic',
                'categories': [f['check_name'] for f in prescreen['findings']],
                'analysis': '; '.join(f['details'] for f in prescreen['findings']),
                'flagged': False,
                'requires_human_review': False,
            }

        # ── Moderate findings: deterministic flagged something ambiguous ──
        # This is the ONLY case where LLM adds value — interpreting whether
        # a flagged phrase is genuinely discriminatory or a false positive
        # (e.g., prohibited term appearing in a legal disclosure context).
        logger.info('Bias pre-screen: moderate findings, deterministic_score=%d — invoking LLM for interpretation', det_score)

        sanitized_email = _sanitize_prompt_input(email_text, max_length=5000)
        sanitized_purpose = _sanitize_prompt_input(str(application_context.get('purpose', 'N/A')), max_length=200)
        sanitized_decision = _sanitize_prompt_input(str(application_context.get('decision', 'N/A')), max_length=20)
        prescreen_summary = self._format_prescreen_results(prescreen)

        prompt = f"""You are a compliance analyst at an Australian bank called AussieLoanAI. Your deterministic compliance system has flagged potential issues in a loan decision email. Your job is to determine whether the flags are genuine bias concerns or false positives.

=== EMAIL TEXT ===
{sanitized_email}

=== APPLICATION CONTEXT ===
- Loan Amount: ${application_context.get('loan_amount', 'N/A')}
- Purpose: {sanitized_purpose}
- Decision: {sanitized_decision}

=== DETERMINISTIC FLAGS ===
{prescreen_summary}

=== YOUR TASK ===
The deterministic system flagged this email with a score of {det_score}/100. Review the specific flags above and determine:
1. Are any of the flagged phrases genuinely discriminatory, or are they false positives (e.g., legal disclosures, standard financial terminology)?
2. Did the deterministic system miss any subtle bias the flags hint at?

=== SCORING ===
- If the flags are false positives (legal disclosures, standard terms): score 0-30.
- If the flags reveal genuine bias concerns: score matching the severity (40-100).
- Standard financial language (income, credit score, DTI, employment tenure) is NEVER bias.
- Legal disclosures referencing discrimination Acts are REQUIRED BY LAW, not evidence of bias.

Use the record_bias_analysis tool to submit your findings."""

        fallback = {
            'score': det_score,
            'categories': [f['check_name'] for f in prescreen['findings']],
            'analysis': 'LLM interpretation unavailable — using deterministic score.',
        }

        try:
            response = self.client.messages.create(
                model='claude-sonnet-4-20250514',
                max_tokens=1024,
                temperature=getattr(django_settings, 'AI_TEMPERATURE_ANALYSIS', 0.0),
                messages=[{'role': 'user', 'content': prompt}],
                tools=[BIAS_ANALYSIS_TOOL],
                tool_choice={'type': 'tool', 'name': 'record_bias_analysis'},
            )
            result = _extract_tool_result(response, fallback)
        except Exception as e:
            logger.error('LLM bias interpretation failed: %s — falling back to deterministic', e)
            result = fallback

        llm_raw_score = result.get('score', det_score)

        # Final score: deterministic is the anchor, LLM adjusts.
        # If LLM says it's a false positive (low score), trust it — that's why we called the LLM.
        # If LLM confirms bias (high score), use the higher of the two.
        if llm_raw_score <= 30:
            final_score = llm_raw_score
        else:
            final_score = max(det_score, llm_raw_score)

        return {
            'score': final_score,
            'deterministic_score': det_score,
            'llm_raw_score': llm_raw_score,
            'score_source': 'deterministic_with_llm_interpretation',
            'categories': result.get('categories', []),
            'analysis': result.get('analysis', ''),
            'flagged': final_score > bias_threshold_pass,
            'requires_human_review': bias_threshold_pass < final_score <= bias_threshold_review,
        }

    def _format_prescreen_results(self, prescreen):
        """Format pre-screen results for injection into the LLM prompt."""
        lines = []
        checks = {
            'prohibited_language': 'Prohibited language',
            'tone_check': 'Tone',
            'professional_financial_language': 'Professional language',
            'ai_giveaway_language': 'AI giveaway language',
        }
        triggered_names = {f['check_name'] for f in prescreen['findings']}
        for check_name, label in checks.items():
            status = 'FAILED' if check_name in triggered_names else 'PASSED'
            lines.append(f'- {label}: {status}')
        lines.append(f"- Pre-screen score: {prescreen['deterministic_score']}/100")
        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Agent 2: Head of Compliance — senior review using a tougher model (Opus)
# ---------------------------------------------------------------------------

class AIEmailReviewer:
    """Head of Compliance who reviews emails flagged by the junior analyst.

    Role: You are the Head of Compliance at an Australian bank. You have 18 years
    in financial services regulation. You have seen three Royal Commissions. You
    do not rubber-stamp your analyst's work — you interrogate it. If the junior
    flagged something, you determine whether the flag is genuine or a false
    positive. But you also look for things the junior MISSED: subtle framing,
    coded language, implications that a less experienced analyst would overlook.

    You are tougher than the junior, not softer. You use a stronger model because
    your judgment carries more weight — if you approve, the email ships.
    """

    # Use Opus for the senior reviewer — tougher model, harder to fool
    MODEL = 'claude-opus-4-20250514'

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is not set')
        self.client = anthropic.Anthropic(api_key=api_key)

    def review(self, email_text, bias_result, application_context):
        """Review a flagged email as the senior compliance authority."""
        sanitized_email = _sanitize_prompt_input(email_text, max_length=5000)
        sanitized_analysis = _sanitize_prompt_input(str(bias_result.get('analysis', 'N/A')), max_length=2000)
        sanitized_purpose = _sanitize_prompt_input(str(application_context.get('purpose', 'N/A')), max_length=200)
        sanitized_decision = _sanitize_prompt_input(str(application_context.get('decision', 'N/A')), max_length=20)

        prompt = f"""You are the Head of Compliance at AussieLoanAI, an Australian bank. You have 18 years in financial services regulation. You lived through the Hayne Royal Commission and know its specific recommendations:
- Recommendation 1.1: Banks must act in the customer's best interests, not pass credit risk to consumers
- Recommendation 4.9: No hawking of financial products
- Recommendation 4.10: Do not cross-sell to vulnerable customers post-decline

You have personally drafted remediation programs after ASIC enforcement actions. You do not get nervous about compliance — you get precise.

Your junior analyst flagged the following loan decision email with a bias score of {bias_result.get('score', 0)}/100. The email has landed on your desk.

Your job is NOT to rubber-stamp. You do two things:

1. INTERROGATE the junior's finding: Was it a genuine flag or a false positive? Junior analysts over-flag standard financial language. If the flagged phrase is just "debt-to-income ratio" or "employment tenure," dismiss it.

2. LOOK FOR WHAT THE JUNIOR MISSED: Read the full email yourself. Your analyst is two years in — they catch obvious phrases but miss subtle framing, coded language, tone shifts, and implications. A sentence can be individually compliant but discriminatory in context.

=== JUNIOR ANALYST'S FINDINGS ===
Score: {bias_result.get('score', 0)}/100
Categories flagged: {', '.join(bias_result.get('categories', [])) or 'None'}
Analysis: {sanitized_analysis}

=== EMAIL TEXT ===
{sanitized_email}

=== APPLICATION CONTEXT ===
- Loan Amount: ${application_context.get('loan_amount', 'N/A')}
- Purpose: {sanitized_purpose}
- Decision: {sanitized_decision}

=== YOUR DECISION FRAMEWORK ===
Ask yourself these questions as a banker who has seen enforcement actions:

1. If ASIC pulled this email in a compliance audit, would I have to explain anything? If yes, it fails.
2. Would a customer from any protected group read this email differently than another customer? If yes, it fails.
3. Is the language appropriate for a Big 4 bank in 2025? Would CBA, Westpac, ANZ, or NAB send this exact email? If not, why not?
4. Would this email satisfy a Banking Code of Practice 2025 compliance audit under para 81-91?
5. Did my junior flag something that is actually just standard lending language? If yes, overrule the flag.

=== ASIC POST-HAYNE ENFORCEMENT PRIORITIES ===
- Responsible lending violations (NCCP Act s 131, s 133)
- Misleading advertising about credit terms (RG 234)
- Pressure tactics targeting vulnerable customers
- Cross-selling without suitability assessment (Firstmac Federal Court case 2024)

Relevant legislation:
- Sex Discrimination Act 1984 (s 22)
- Racial Discrimination Act 1975 (s 15)
- Disability Discrimination Act 1992 (s 24)
- Age Discrimination Act 2004 (s 26)
- NCCP Act 2009 (s 131, s 133, s 136) — responsible lending obligations
- Banking Code of Practice 2025 (para 81-91)

Use the record_review_decision tool to submit your decision."""

        fallback = {
            'approved': False,
            'confidence': 0.0,
            'reasoning': 'Unable to parse senior review response, defaulting to human escalation.',
        }

        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=1024,
            temperature=getattr(django_settings, 'AI_TEMPERATURE_ANALYSIS', 0.0),
            messages=[{'role': 'user', 'content': prompt}],
            tools=[EMAIL_REVIEW_TOOL],
            tool_choice={'type': 'tool', 'name': 'record_review_decision'},
        )

        result = _extract_tool_result(response, fallback)

        return {
            'approved': result.get('approved', False),
            'confidence': result.get('confidence', 0.0),
            'reasoning': result.get('reasoning', ''),
        }


# ---------------------------------------------------------------------------
# Agent 3: Marketing Compliance Analyst — bias detection for marketing emails
# ---------------------------------------------------------------------------

class MarketingBiasDetector:
    """Compliance analyst screening marketing/retention emails for bias.

    Marketing emails have different risk vectors than decision emails:
    - Patronising language toward declined customers
    - Pressure tactics or false urgency to push alternative products
    - Discriminatory targeting of products (e.g. steering lower-value products
      to certain demographics)
    - False promises about approval odds for alternative products
    - Language that makes the customer feel "lesser" for being declined
    """

    MARKETING_BIAS_CATEGORIES = [
        'patronising_tone',
        'pressure_tactics',
        'discriminatory_product_steering',
        'false_promises',
        'gender', 'race', 'age', 'religion', 'disability', 'marital_status',
    ]

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is not set')
        self.client = anthropic.Anthropic(api_key=api_key)
        self.prescreener = DeterministicBiasPreScreen()

    def analyze(self, email_text, application_context):
        """Score marketing email for bias using deterministic-first approach.

        Same principle as decision emails: deterministic compliance checklist
        is the primary gate. LLM is only invoked for ambiguous flags.
        Marketing emails have additional checks (patronising tone, pressure
        tactics, false urgency) but the flow is identical.
        """
        prescreen = self.prescreener.prescreen_marketing_email(email_text, application_context)
        det_score = prescreen['deterministic_score']

        mkt_pass = getattr(django_settings, 'MARKETING_BIAS_THRESHOLD_PASS', 50)
        mkt_review = getattr(django_settings, 'MARKETING_BIAS_THRESHOLD_REVIEW', 70)

        # ── Clean email: all deterministic checks passed ──
        if prescreen['all_clean']:
            logger.info('Marketing bias pre-screen: all checks passed, score=%d — compliant', det_score)
            return {
                'score': det_score,
                'deterministic_score': det_score,
                'llm_raw_score': None,
                'score_source': 'deterministic',
                'categories': [],
                'analysis': 'All deterministic compliance checks passed. No bias detected.',
                'flagged': False,
                'requires_human_review': False,
            }

        # ── Severe violation ──
        if det_score > mkt_review:
            logger.warning('Marketing bias pre-screen: severe violation, score=%d — blocking', det_score)
            return {
                'score': det_score,
                'deterministic_score': det_score,
                'llm_raw_score': None,
                'score_source': 'deterministic',
                'categories': [f['check_name'] for f in prescreen['findings']],
                'analysis': '; '.join(f['details'] for f in prescreen['findings']),
                'flagged': True,
                'requires_human_review': True,
            }

        # ── Minor findings ──
        if det_score <= mkt_pass:
            logger.info('Marketing bias pre-screen: minor findings, score=%d — compliant', det_score)
            return {
                'score': det_score,
                'deterministic_score': det_score,
                'llm_raw_score': None,
                'score_source': 'deterministic',
                'categories': [f['check_name'] for f in prescreen['findings']],
                'analysis': '; '.join(f['details'] for f in prescreen['findings']),
                'flagged': False,
                'requires_human_review': False,
            }

        # ── Moderate findings: LLM interprets ambiguous flags ──
        logger.info('Marketing bias pre-screen: moderate findings, score=%d — invoking LLM', det_score)

        sanitized_email = _sanitize_prompt_input(email_text, max_length=5000)
        sanitized_purpose = _sanitize_prompt_input(str(application_context.get('purpose', 'N/A')), max_length=200)
        prescreen_summary = self._format_prescreen_results(prescreen)

        prompt = f"""You are a compliance analyst at AussieLoanAI. Your deterministic compliance system has flagged potential issues in a marketing email to a declined loan customer. Determine whether the flags are genuine concerns or false positives.

=== EMAIL TEXT ===
{sanitized_email}

=== CUSTOMER CONTEXT ===
- Originally requested: ${application_context.get('loan_amount', 'N/A')} for {sanitized_purpose}
- Decision: Declined

=== DETERMINISTIC FLAGS ===
{prescreen_summary}

=== YOUR TASK ===
The deterministic system flagged this email with a score of {det_score}/100. Review the flags and determine:
1. Are the flagged phrases genuinely patronising, pressuring, or discriminatory?
2. Or are they false positives (warm professional tone, standard product offers, legitimate retention language)?

=== SCORING ===
- False positives (professional tone, standard offers): score 0-30.
- Genuine concerns (pressure tactics, patronising language, discriminatory steering): score matching severity (40-100).
- Presenting alternative products with real numbers is the POINT of retention emails, not bias.
- Referencing customer's banking relationship (tenure, payments, savings) for product matching is legitimate.

Use the record_marketing_bias_analysis tool to submit your findings."""

        fallback = {
            'score': det_score,
            'categories': [f['check_name'] for f in prescreen['findings']],
            'analysis': 'LLM interpretation unavailable — using deterministic score.',
        }

        try:
            response = self.client.messages.create(
                model='claude-sonnet-4-20250514',
                max_tokens=1024,
                temperature=getattr(django_settings, 'AI_TEMPERATURE_ANALYSIS', 0.0),
                messages=[{'role': 'user', 'content': prompt}],
                tools=[MARKETING_BIAS_TOOL],
                tool_choice={'type': 'tool', 'name': 'record_marketing_bias_analysis'},
            )
            result = _extract_tool_result(response, fallback)
        except Exception as e:
            logger.error('LLM marketing bias interpretation failed: %s — falling back to deterministic', e)
            result = fallback

        llm_raw_score = result.get('score', det_score)
        # If LLM says false positive (low score), trust it — that's why we called the LLM.
        if llm_raw_score <= 30:
            final_score = llm_raw_score
        else:
            final_score = max(det_score, llm_raw_score)

        return {
            'score': final_score,
            'deterministic_score': det_score,
            'llm_raw_score': llm_raw_score,
            'score_source': 'deterministic_with_llm_interpretation',
            'categories': result.get('categories', []),
            'analysis': result.get('analysis', ''),
            'flagged': final_score > mkt_pass,
            'requires_human_review': mkt_pass < final_score <= mkt_review,
        }

    def _format_prescreen_results(self, prescreen):
        """Format pre-screen results for injection into the LLM prompt."""
        lines = []
        checks = {
            'prohibited_language': 'Prohibited language',
            'tone_check': 'Tone',
            'professional_financial_language': 'Professional language',
            'decline_language': 'Decline references',
            'patronising_language': 'Patronising language',
            'false_urgency': 'False urgency',
            'guaranteed_approval': 'Guaranteed approval claims',
        }
        triggered_names = {f['check_name'] for f in prescreen['findings']}
        for check_name, label in checks.items():
            status = 'FAILED' if check_name in triggered_names else 'PASSED'
            lines.append(f'- {label}: {status}')
        lines.append(f"- Pre-screen score: {prescreen['deterministic_score']}/100")
        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Agent 4: Marketing Head of Compliance — senior review for marketing emails
# ---------------------------------------------------------------------------

class MarketingEmailReviewer:
    """Senior compliance review for marketing emails, using a tougher model.

    Role: Same Head of Compliance, but now reviewing marketing material. You know
    that marketing to declined customers is where banks get into trouble with ASIC.
    You have seen remediation programs where banks had to refund customers who
    were sold unsuitable products after a decline. You are protective of the
    customer — if there is any doubt, the email does not ship.

    But you are also a banker. You understand that retention is legitimate. A good
    alternative offer genuinely helps the customer. Your job is to tell the
    difference between helpful retention and exploitative cross-selling.
    """

    MODEL = 'claude-opus-4-20250514'

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is not set')
        self.client = anthropic.Anthropic(api_key=api_key)

    def review(self, email_text, bias_result, application_context):
        """Senior review of a flagged marketing email."""
        sanitized_email = _sanitize_prompt_input(email_text, max_length=5000)
        sanitized_analysis = _sanitize_prompt_input(str(bias_result.get('analysis', 'N/A')), max_length=2000)
        sanitized_purpose = _sanitize_prompt_input(str(application_context.get('purpose', 'N/A')), max_length=200)

        prompt = f"""You are the Head of Compliance at AussieLoanAI. You are reviewing a marketing follow-up email to a customer whose loan was declined. Your junior analyst flagged it with a score of {bias_result.get('score', 0)}/100.

You have 18 years in banking compliance. You know the Hayne Royal Commission's specific findings:
- Recommendation 1.1: Banks must act in the customer's best interests
- Recommendation 4.9: No hawking of financial products
- Recommendation 4.10: Do not cross-sell to vulnerable customers post-decline

You know that marketing to declined customers is where regulators pay the closest attention. ASIC's RG 234, the NCCP Act 2009 (s 131, s 133), and the Banking Code of Practice 2025 (para 89-91) are your reference points.

But you are also a banker who understands retention. A customer who was declined for a $500,000 home loan might genuinely benefit from a $15,000 secured personal loan. The question is not whether we offer alternatives — it is HOW we offer them.

=== JUNIOR ANALYST'S FINDINGS ===
Score: {bias_result.get('score', 0)}/100
Categories flagged: {', '.join(bias_result.get('categories', [])) or 'None'}
Analysis: {sanitized_analysis}

=== EMAIL TEXT ===
{sanitized_email}

=== CUSTOMER CONTEXT ===
- Originally requested: ${application_context.get('loan_amount', 'N/A')} for {sanitized_purpose}
- Decision: Declined

=== YOUR DECISION FRAMEWORK ===

1. WOULD ASIC OBJECT? If this email appeared in an ASIC compliance review of your marketing practices to declined customers, would you need to explain it? If yes, it fails. Key enforcement priorities: responsible lending violations, misleading advertising (RG 234), pressure tactics on vulnerable customers, cross-selling without suitability assessment (Firstmac Federal Court case 2024).

2. IS THE TONE RIGHT? The customer just got declined. Are we treating them with dignity, or are we immediately trying to sell them something else? There is a difference between "here are some options that may suit you" and "don't worry, we have other products!"

3. ARE THE PRODUCTS APPROPRIATE? Based on the context, do the offered alternatives seem financially appropriate for this customer, or does it look like product-pushing?

4. BANKING CODE COMPLIANCE? Would this email satisfy a Banking Code of Practice 2025 audit under para 89-91? Marketing must not be aggressive or misleading.

5. DID THE JUNIOR GET IT RIGHT? Over-flagging wastes time. If the junior flagged "warm professional tone" as patronising, overrule it. But if the junior missed subtle pressure language, catch it.

6. WOULD A BIG 4 BANK SEND THIS? Would CBA, Westpac, ANZ, or NAB send this exact email to a declined customer? If not, why not?

Use the record_marketing_review_decision tool to submit your decision."""

        fallback = {
            'approved': False,
            'confidence': 0.0,
            'reasoning': 'Unable to parse senior marketing review — defaulting to human escalation.',
        }

        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=1024,
            temperature=getattr(django_settings, 'AI_TEMPERATURE_ANALYSIS', 0.0),
            messages=[{'role': 'user', 'content': prompt}],
            tools=[MARKETING_REVIEW_TOOL],
            tool_choice={'type': 'tool', 'name': 'record_marketing_review_decision'},
        )

        result = _extract_tool_result(response, fallback)

        return {
            'approved': result.get('approved', False),
            'confidence': result.get('confidence', 0.0),
            'reasoning': result.get('reasoning', ''),
        }
