import logging

from django.conf import settings as django_settings

from utils.sanitization import sanitize_prompt_input as _sanitize_prompt_input

from .helpers import _call_with_retry, _make_anthropic_client
from .tools import EMAIL_REVIEW_TOOL

logger = logging.getLogger("agents.bias_detector")


# ---------------------------------------------------------------------------
# Agent 2: Head of Compliance — senior review using a tougher model (Opus)
# ---------------------------------------------------------------------------


class AIEmailReviewer:
    """Head of Compliance who does a holistic review of flagged emails.

    Mandate: The junior analyst and deterministic system already classified
    specific flags (prohibited language, tone, etc). The senior's job is
    DIFFERENT, not a stricter version of the same check. The senior reads the
    email as a whole and looks for things regex and a junior analyst cannot
    catch: subtle framing, coded language, contextual implications, tone shifts
    that are individually compliant but discriminatory in aggregate.

    Uses Opus (stronger model) because this requires deeper reasoning and the
    decision carries more weight — if the senior approves, the email ships.
    """

    # Use Opus for the senior reviewer — tougher model, harder to fool
    MODEL = "claude-opus-4-7"

    def __init__(self):
        self.client = _make_anthropic_client()

    def review(self, email_text, bias_result, application_context):
        """Review a flagged email as the senior compliance authority.

        The senior's mandate is DIFFERENT from the junior's, not stricter on the
        same task. The junior classified deterministic flags. The senior does a
        holistic review looking for things regex and a junior analyst cannot catch:
        subtle framing, coded language, contextual implications, tone shifts.
        """
        sanitized_email = _sanitize_prompt_input(email_text, max_length=5000)
        sanitized_analysis = _sanitize_prompt_input(str(bias_result.get("analysis", "N/A")), max_length=2000)
        sanitized_purpose = _sanitize_prompt_input(str(application_context.get("purpose", "N/A")), max_length=200)
        sanitized_decision = _sanitize_prompt_input(str(application_context.get("decision", "N/A")), max_length=20)

        prompt = f"""You are the Head of Compliance at AussieLoanAI, an Australian bank. You have 18 years in financial services regulation. You lived through the Hayne Royal Commission. You have personally drafted remediation programs after ASIC enforcement actions. You do not get nervous about compliance. You get precise.

=== WHAT HAS ALREADY BEEN CHECKED ===
Your junior analyst and the deterministic system have ALREADY handled the following:
- Prohibited language patterns (regex check against Australian discrimination Acts)
- Tone violations (aggressive or inappropriate language)
- Professional financial language compliance
- Informal tone detection
- The junior classified each flag as genuine or false positive

Junior's score: {bias_result.get("score", 0)}/100
Junior's flag classifications: {sanitized_analysis}
Categories the junior flagged: {", ".join(bias_result.get("categories", [])) or "None"}

DO NOT re-check what the junior already covered. That work is done. If the junior flagged "debt-to-income ratio" as bias, that is not your problem to fix. Your job is different.

=== YOUR MANDATE (different from the junior's) ===
Read this email with 18 years of experience and look for what a two-year analyst and a regex engine CANNOT catch:

1. SUBTLE FRAMING: Does the email frame the customer's situation in a way that implies judgment about who they are rather than what their finances look like? A sentence can be individually compliant but discriminatory in context.

2. CODED LANGUAGE: Are there phrases that a sophisticated reader from a protected group would recognise as loaded, even though they pass a literal compliance check?

3. CONTEXTUAL IMPLICATIONS: Given this is a {sanitized_decision} for ${application_context.get("loan_amount", "N/A")} ({sanitized_purpose}), does the tone match what a Big 4 bank (CBA, Westpac, ANZ, NAB) would send? Would you sign off on this going out under your name?

4. REGULATORY RISK: If ASIC pulled this email in a compliance audit, would you have to explain anything beyond standard lending language? Would it satisfy Banking Code of Practice 2025 para 81-91?

5. CUSTOMER IMPACT: Would a customer from any protected group read this email differently than another customer receiving the same decision?

6. CONTEXTUAL DIGNITY: Does the email label the PERSON rather than describe the SITUATION? BAD: "You are unemployed" / "You cannot afford this" / "Your poor credit" / "You are a high risk". GOOD: "Your employment status at the time of application" / "The requested amount exceeded our serviceability thresholds" / "Your credit profile at the time of assessment" / "The risk profile of this application". A customer who was made redundant did not "fail" at anything.

7. PSYCHOLOGICAL SAFETY (Hayne Commission + ABA Guideline 2025):
   - FRAMING: Does the email frame the denial around what the customer CANNOT have, or pivot to what they CAN do? Gain-framed messages produce 15-30% better perception.
   - LOSS AVERSION: Does it use finality language ("this decision is final", "nothing more we can do")? Finality triggers 2x the emotional pain. Frame as "not yet."
   - INSTITUTIONAL COLDNESS (Hayne): Does it sound like "the bank" or like Sarah Mitchell? "The bank has determined", "per our policy", "our systems indicate" = power imbalance.
   - COGNITIVE LOAD: Are there sentences over 35 words a distressed customer would struggle with?
   - PEAK-END RULE: Does the closing leave the customer feeling valued or dismissed? Generic "we wish you well" = brush-off. Strong closings use their name and offer a concrete next step.
   Apply the "read it aloud" test: read the email as if you are the customer who just lost their job. If any sentence makes you wince, flag it.

=== EMAIL TEXT ===
{sanitized_email}

=== APPLICATION CONTEXT ===
- Loan Amount: ${application_context.get("loan_amount", "N/A")}
- Purpose: {sanitized_purpose}
- Decision: {sanitized_decision}

=== RELEVANT LEGISLATION (for your reference, not for re-checking) ===
- Sex Discrimination Act 1984 (s 22)
- Racial Discrimination Act 1975 (s 15)
- Disability Discrimination Act 1992 (s 24)
- Age Discrimination Act 2004 (s 26)
- NCCP Act 2009 (s 131, s 133, s 136)
- Banking Code of Practice 2025 (para 81-91)
- Hayne Royal Commission Recommendations 1.1, 4.9, 4.10

=== YOUR DECISION ===
- approved=true means: "I have read this email with 18 years of experience and I see nothing that the junior and the regex missed. This email is safe to send."
- approved=false means: "I found something the junior missed. This needs human review."
- confidence reflects how certain you are. Below 0.70 triggers human escalation even if you approve, because the stakes are too high for a maybe.

Use the record_review_decision tool to submit your decision."""

        fallback = {
            "approved": False,
            "confidence": 0.0,
            "reasoning": "Unable to parse senior review response, defaulting to human escalation.",
        }

        result = _call_with_retry(
            self.client,
            fallback,
            "Senior review",
            "defaulting to human escalation",
            model=self.MODEL,
            max_tokens=1024,
            temperature=getattr(django_settings, "AI_TEMPERATURE_ANALYSIS", 0.0),
            messages=[{"role": "user", "content": prompt}],
            tools=[EMAIL_REVIEW_TOOL],
            tool_choice={"type": "tool", "name": "record_review_decision"},
        )

        return {
            "approved": result.get("approved", False),
            "confidence": result.get("confidence", 0.0),
            "reasoning": result.get("reasoning", ""),
        }
