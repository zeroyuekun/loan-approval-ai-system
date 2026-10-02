"""The template decision emails read like a person wrote them.

Stock phrases a reader recognises as form-letter or machine text are kept out
of the deterministic templates, the denial opening says the outcome once, and
dashes are not used as sentence punctuation (ranges such as 1–2 or Mon–Fri
are fine).
"""

import re

import pytest

from apps.email_engine.services.guardrails import GuardrailChecker
from apps.email_engine.services.template_fallback import (
    generate_approval_template,
    generate_conditional_template,
    generate_denial_template,
)

STOCK_PHRASES = [
    "don't hesitate",
    "simply reply",
    "we are pleased to advise",
    "thank you for giving us the opportunity",
    "carefully reviewed",
    "thorough review",
    "this assessment was conducted",
    "you will have access to",
    "is here to help and can be reached",
]

# A dash with a space on either side is sentence punctuation; an unspaced
# en dash between two tokens is a range and stays.
PUNCTUATION_DASH = re.compile(r"\s[–—]\s|[A-Za-z][—][A-Za-z]")

# Name/value lines rather than sentences: the bureau list ("Equifax – equifax.com.au")
# and attachment file names ("Loan Contract – Jane Citizen.pdf").
NAME_PAIR_LINE = re.compile(r"^\s*(•\s+(Equifax|Illion|Experian) – |\d+\.\s.*\.pdf$)")

PRICING = {
    "interest_rate": "6.49% p.a.",
    "rate_type": "Variable",
    "comparison_rate": "6.71% p.a.",
    "loan_term_display": "5 years",
    "monthly_payment": "$586.40",
    "establishment_fee": "$250",
    "first_repayment_date": "1 November 2026",
}


def _emails():
    return {
        "approval_personal": generate_approval_template("Jane Citizen", 30000, "personal", pricing=PRICING),
        "approval_home_couple": generate_approval_template(
            "Jane Citizen", 650000, "home", pricing=PRICING, applicant_type="Couple"
        ),
        "approval_conditional": generate_conditional_template(
            "Jane Citizen", 30000, "personal", conditions=["Payslips"], pricing=PRICING
        ),
        "denial_reasons": generate_denial_template(
            "Jane Citizen",
            25000,
            "personal",
            denial_reasons=(
                "Debt-to-income ratio above acceptable range;"
                "Your deposit size and income stability together don't meet our lending requirements right now"
            ),
        ),
        "denial_no_reasons": generate_denial_template("Jane Citizen", 25000, "personal"),
    }


def _prose(body):
    """The letter text above the footer rule, without name/value lines.

    The footer is fixed regulatory copy.
    """
    letter = body.split("─" * 10)[0]
    return "\n".join(line for line in letter.splitlines() if not NAME_PAIR_LINE.match(line))


@pytest.mark.parametrize("name", list(_emails()))
def test_template_has_no_stock_phrases(name):
    text = _prose(_emails()[name]["body"]).lower()
    found = [p for p in STOCK_PHRASES if p in text]
    assert not found, f"{name}: stock phrases {found}"


@pytest.mark.parametrize("name", list(_emails()))
def test_template_does_not_use_dashes_as_punctuation(name):
    text = _prose(_emails()[name]["body"])
    assert not PUNCTUATION_DASH.search(text), PUNCTUATION_DASH.search(text)


def test_denial_states_the_outcome_once_and_leads_into_the_factors():
    body = _emails()["denial_reasons"]["body"]
    assert "unable to offer you credit" in body
    assert "Here is what we looked at" not in body
    assert "This decision was based on" not in body
    opening, _, rest = body.partition("The main factors in our decision:")
    assert rest, "the factor list needs its lead-in line"
    assert rest.lstrip().startswith("•"), "the lead-in goes straight into the factor bullets"


def test_approval_congratulates_once_in_the_letter():
    body = _emails()["approval_personal"]["body"]
    assert body.count("Congratulations") == 1


AMOUNTS = {"approval_home_couple": 650000, "denial_reasons": 25000, "denial_no_reasons": 25000}


@pytest.mark.parametrize("name", list(_emails()))
def test_template_still_passes_every_guardrail(name):
    """Same checks and pass rule as EmailGenerator._generate_fallback, plus the
    LLM-only AI-giveaway check: the templates are held to the LLM's standard."""
    email = _emails()[name]
    decision = "approved" if name.startswith("approval") else "denied"
    context = {
        "decision": decision,
        "applicant_name": "Jane Citizen",
        "loan_amount": float(AMOUNTS.get(name, 30000)),
        "purpose": "Personal",
    }
    if decision == "approved":
        context["pricing"] = PRICING
    checker = GuardrailChecker()
    results = checker.run_all_checks(email["body"], context, template_mode=True)
    results.append(checker.check_ai_giveaway_language(email["body"]))
    failed = [(r["check_name"], r["details"]) for r in results if not r["passed"] and r.get("severity") != "warning"]
    assert not failed, f"{name}: {failed}"


TEMPLATE_MARKER = "=== TEMPLATE (USE AS-IS) ==="


def _prompt_template_block(prompt):
    return prompt[prompt.index(TEMPLATE_MARKER) :]


@pytest.mark.parametrize("prompt_name", ["APPROVAL_EMAIL_PROMPT", "DENIAL_EMAIL_PROMPT"])
def test_llm_prompt_template_has_no_stock_phrases(prompt_name):
    """The LLM copies the prompt's template verbatim, so it must read the same
    way as the deterministic template."""
    from apps.email_engine.services import prompts

    block = _prompt_template_block(getattr(prompts, prompt_name)).lower()
    found = [p for p in STOCK_PHRASES if p in block]
    assert not found, f"{prompt_name}: stock phrases {found}"


def test_llm_denial_prompt_template_matches_the_deterministic_denial():
    from apps.email_engine.services.prompts import DENIAL_EMAIL_PROMPT

    block = _prompt_template_block(DENIAL_EMAIL_PROMPT)
    template = _emails()["denial_reasons"]["body"]
    for line in (
        "we are unable to offer you credit at this time. Those obligations require any credit we offer "
        "to be suitable and manageable for you.",
        "The main factors in our decision:",
        "If you have questions about this decision, call me on 1300 000 000",
        "When you're ready, we'd like to help you find the right option.",
    ):
        assert line in template
        assert line in block, line


def test_llm_approval_prompt_template_matches_the_deterministic_approval():
    from apps.email_engine.services.prompts import APPROVAL_EMAIL_PROMPT

    block = _prompt_template_block(APPROVAL_EMAIL_PROMPT)
    template = _emails()["approval_home_couple"]["body"]
    for line in (
        "with AussieLoanAI has been approved. Congratulations!",
        "After you sign, there is a cooling-off period in which you can withdraw without penalty.",
        "Our Financial Hardship team can work through options with you on 1300 000 001",
        "If you have questions about your loan or the next steps, call me on 1300 000 000",
    ):
        assert line in template
        assert line in block, line
    assert block.count("Congratulations") == 2, "the subject line and the opening only"
