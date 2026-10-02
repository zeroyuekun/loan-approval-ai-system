"""Issuing decision emails (approval / denial) to the applicant.

One service for every path that issues a decision notice: the orchestrator's
email step, the human-review resume and deny outcomes, the standalone
``generate_email_task``, the staff "send latest" endpoint and the decision
review overturn. Before this module each path had its own generate / fallback /
send / ``sent_at`` semantics, which is how a decided application could end up
with no notice (guardrail exhaustion, a 429) or with two (a send that never
stamped ``sent_at``).

Guarantees:

* The decision an email announces always comes from the application's
  ``LoanDecision`` record when a caller asks for it to be checked
  (``require_decision_on_record``), never from a caller-supplied value: an
  approval letter carries a rate, repayments and a sign-by date.
* ``generate_decision_email`` never leaves the caller without a compliant
  email for provider trouble: LLM/provider errors, a closed budget gate and
  guardrail exhaustion degrade to the deterministic template inside
  ``EmailGenerator``; a 429 degrades to the template here unless the caller
  can retry itself (the Celery task, ``on_rate_limit="raise"``).
* ``deliver_decision_email`` sends at most once per row: the send runs under a
  row lock and only while ``sent_at`` is unset, and a successful send stamps
  ``sent_at``. Delivery is at-least-once across a crash between SMTP accept
  and COMMIT.
* ``issue_decision_email`` and ``generate_email_task`` bias-check what they
  generate before sending (``deliver_screened_decision_email``), as the
  orchestrator and the human-review resume do.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.email_engine.models import GeneratedEmail
from apps.email_engine.services import sender
from apps.email_engine.services.email_generator import EmailGenerator
from apps.email_engine.services.exceptions import RateLimited
from apps.email_engine.services.persistence import EmailPersistenceService
from apps.loans.models import LoanDecision

logger = logging.getLogger("email_engine.decision_email")


class DecisionMismatch(ValueError):
    """The requested decision email disagrees with the decision on record."""


class HeldForBiasReview(ValueError):
    """The decision email is held back by the bias review.

    Only the human-review paths (approve / deny / regenerate) may release or
    replace it, because they re-run the bias check before anything is sent.
    """


def bias_hold_reason(application_id, email=None):
    """Why no staff send/generate may run for this application, or None.

    * The application is under human review (status REVIEW or an escalated
      AgentRun): the reviewer's outcome decides the email.
    * ``email`` is an unsent draft with a flagged bias report: the pipeline
      withheld it, so re-sending it would bypass the bias check. A flagged
      draft that the pipeline then sent has ``sent_at`` set and is not held.
    * ``email`` is an unsent Agent 2 rewrite the senior reviewer has not
      approved: its report has ``ai_review_approved=False`` from the moment it
      is persisted until the review approves it, so a rejected rewrite, or one
      whose review never finished (a time limit or crash mid-Agent 2), stays
      held. Reports with no senior review (``None``) do not hold a draft.
    """
    from django.db.models import Q

    from apps.agents.models import AgentRun
    from apps.loans.models import LoanApplication

    under_review = (
        LoanApplication.objects.filter(pk=application_id, status=LoanApplication.Status.REVIEW).exists()
        or AgentRun.objects.filter(application_id=application_id, status=AgentRun.Status.ESCALATED).exists()
    )
    if under_review:
        return "Application is under human review; the review outcome issues the decision email"
    if (
        email is not None
        and email.sent_at is None
        and email.bias_reports.filter(Q(flagged=True) | Q(ai_review_approved=False)).exists()
    ):
        return (
            "The stored draft was held back by the bias check and cannot be sent; "
            "re-run the pipeline to issue a freshly screened email"
        )
    return None


def decision_on_record(application_id):
    """Return ``"approved"``/``"denied"`` from LoanDecision, or None if undecided."""
    return LoanDecision.objects.filter(application_id=application_id).values_list("decision", flat=True).first()


def require_decision_on_record(application_id, requested=None):
    """Return the recorded decision, refusing when there is none or it disagrees.

    ``requested=None`` means "whatever is on record".
    """
    recorded = decision_on_record(application_id)
    if recorded is None:
        raise DecisionMismatch(f"Application {application_id} has no decision on record")
    if requested is not None and requested != recorded:
        raise DecisionMismatch(
            f"Requested a {requested!r} email but the decision on record for application {application_id} "
            f"is {recorded!r}"
        )
    return recorded


def email_type_for(decision):
    return "approval" if decision == "approved" else "denial"


def generate_decision_email(
    application, decision, *, confidence=None, profile_context=None, on_rate_limit="template", generator=None
):
    """Generate and persist the decision email. Returns ``(result, generated_email)``.

    ``on_rate_limit="raise"`` lets a caller that can reschedule itself (the
    Celery email task) retry the LLM later instead of taking the template now.
    """
    generator = generator or EmailGenerator()
    try:
        result = generator.generate(application, decision, confidence=confidence, profile_context=profile_context)
    except RateLimited:
        if on_rate_limit == "raise":
            raise
        logger.warning("Application %s: email LLM rate limited — issuing the template decision email", application.pk)
        result = generator.generate_template(application, decision, profile_context=profile_context)

    return result, _persist(application, decision, result)


def regenerate_decision_email(application, decision, *, confidence, profile_context, bias_feedback, generator=None):
    """Second-agent rewrite of a bias-flagged email. Returns the generator result, NOT persisted.

    The caller (``run_agent2``) persists the rewrite with
    ``persist_decision_email`` only after the bias detector has scored it, in
    the same transaction as its bias report, so a rewrite never exists in the
    database without the report that holds it from the staff send paths until
    the senior review approves it. A template result (LLM unavailable, budget
    gate, guardrail exhaustion) is handed over to the template replacement
    path, which persists its own template. RateLimited propagates.
    """
    generator = generator or EmailGenerator()
    return generator.generate(
        application, decision, confidence=confidence, profile_context=profile_context, bias_feedback=bias_feedback
    )


def persist_decision_email(application, decision, result):
    """Persist a generated decision email and its guardrail logs. Returns the ``GeneratedEmail``."""
    return _persist(application, decision, result)


def generate_template_decision_email(application, decision, *, profile_context=None, generator=None):
    """Generate and persist the deterministic template email. Returns ``(result, generated_email)``.

    Used when the bias check flags an LLM-written email: the template is the
    replacement that gets a second bias check before anything is sent.
    ``profile_context`` carries ``nbo_offer`` for denials, so the replacement
    still carries the next-best offer.
    """
    generator = generator or EmailGenerator()
    result = generator.generate_template(application, decision, profile_context=profile_context)
    return result, _persist(application, decision, result)


def _persist(application, decision, result):
    generated_email = EmailPersistenceService.save_generated_email(application, decision, result)
    EmailPersistenceService.save_guardrail_logs(generated_email, result.get("guardrail_results", []))
    return generated_email


def deliver_decision_email(generated_email):
    """Send a persisted decision email to the applicant exactly once.

    Returns ``{"sent": bool, "already_sent": bool, "recipient": str|None,
    "error": str|None}``. ``sent`` is True only when this call delivered it.
    """
    recipient = generated_email.application.applicant.email or None
    outcome = {"sent": False, "already_sent": False, "recipient": recipient, "error": None}
    if not generated_email.passed_guardrails:
        outcome["error"] = "Email failed guardrails — withheld"
        return outcome
    if not recipient:
        outcome["error"] = "No recipient email address on file"
        return outcome

    with transaction.atomic():
        locked = GeneratedEmail.objects.select_for_update().get(pk=generated_email.pk)
        if locked.sent_at is not None:
            generated_email.sent_at = locked.sent_at
            outcome["already_sent"] = True
            return outcome

        result = sender.send_decision_email(
            recipient,
            locked.subject,
            locked.body,
            email_type=email_type_for(locked.decision),
        )
        if result.get("sent"):
            locked.sent_at = timezone.now()
            locked.save(update_fields=["sent_at"])
            generated_email.sent_at = locked.sent_at
            outcome["sent"] = True
        else:
            outcome["error"] = result.get("error", "Send failed")
    return outcome


def deliver_screened_decision_email(application, decision, result, generated_email, *, profile_context=None):
    """Bias-check a generated email, then send it, its template replacement, or nothing.

    For paths outside the orchestrator and the human-review resume, which run
    their own bias check. See ``screen_and_deliver_decision_email``; returns
    its outcome dict.
    """
    # Imported here: email_engine does not import the agents app at module level.
    from apps.agents.services.decision_email_screening import screen_and_deliver_decision_email

    return screen_and_deliver_decision_email(
        application, decision, result, generated_email, profile_context=profile_context
    )


def issue_decision_email(application, decision, *, confidence=None, profile_context=None, on_rate_limit="template"):
    """Generate, persist, bias-check and (when nothing holds it) deliver the email.

    For callers with no step between generation and delivery. Returns
    ``(result, generated_email, screening_outcome)``; ``generated_email`` is
    the email that was sent or held (the template when it replaced a flagged
    email).
    """
    result, generated_email = generate_decision_email(
        application, decision, confidence=confidence, profile_context=profile_context, on_rate_limit=on_rate_limit
    )
    outcome = deliver_screened_decision_email(
        application, decision, result, generated_email, profile_context=profile_context
    )
    return result, outcome["generated_email"], outcome
