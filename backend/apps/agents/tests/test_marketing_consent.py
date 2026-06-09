"""Regression guard for the marketing-consent reverse-accessor bug (review #2).

The consent gate read `application.applicant.customerprofile`, but the reverse
accessor is `.profile` (CustomerProfile.user has related_name="profile"). The
wrong name raised AttributeError that a bare `except Exception` swallowed, so
consent always read as absent and EVERY marketing email was silently blocked —
even for customers who had explicitly granted consent. The check now lives in
the testable `_has_marketing_consent` helper.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.core.exceptions import ObjectDoesNotExist

from apps.agents.services.marketing_pipeline import MarketingPipelineService


class _Profile:
    def __init__(self, consent: bool):
        self.marketing_consent = consent


class _ApplicantWithoutProfile:
    """Accessing `.profile` raises, like a missing reverse OneToOne relation."""

    @property
    def profile(self):
        raise ObjectDoesNotExist("no profile")


def _application(applicant):
    return SimpleNamespace(applicant=applicant)


def test_consent_granted_returns_true():
    app = _application(SimpleNamespace(profile=_Profile(True)))
    assert MarketingPipelineService._has_marketing_consent(app) is True


def test_consent_declined_returns_false():
    app = _application(SimpleNamespace(profile=_Profile(False)))
    assert MarketingPipelineService._has_marketing_consent(app) is False


def test_missing_profile_returns_false_without_raising():
    app = _application(_ApplicantWithoutProfile())
    assert MarketingPipelineService._has_marketing_consent(app) is False
