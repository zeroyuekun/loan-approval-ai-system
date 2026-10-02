"""Bias record helpers shared by the email pipeline.

Builds the application-facts context the bias detector reads alongside the
email text, and persists the resulting ``BiasReport``.
"""

from apps.agents.models import BiasReport


def bias_context(application, decision):
    """The application facts the bias detector reads alongside the email text."""
    return {
        "loan_amount": float(application.loan_amount),
        "purpose": application.get_purpose_display(),
        "decision": decision,
    }


def save_bias_report(agent_run, generated_email, bias_result, *, ai_review_approved=None):
    """Persist the bias result for ``generated_email``.

    ``ai_review_approved`` records the senior reviewer's verdict on an Agent 2
    rewrite (False while the review is pending or after a rejection); it
    stays None for emails the senior reviewer never sees.
    """
    return BiasReport.objects.create(
        agent_run=agent_run,
        email=generated_email,
        bias_score=bias_result["score"],
        deterministic_score=bias_result.get("deterministic_score"),
        llm_raw_score=bias_result.get("llm_raw_score"),
        score_source=bias_result.get("score_source", "composite"),
        categories=bias_result.get("categories", []),
        analysis=bias_result.get("analysis", ""),
        flagged=bias_result["flagged"],
        requires_human_review=bias_result.get("requires_human_review", bias_result["flagged"]),
        ai_review_approved=ai_review_approved,
    )
