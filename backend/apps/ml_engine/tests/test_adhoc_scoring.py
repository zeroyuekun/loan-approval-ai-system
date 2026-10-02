"""Ad-hoc applicant scoring: dry-run predictor mode + the scoring endpoint.

Task 3 proves `ModelPredictor.predict(app, persist=False)` writes nothing —
no referral-audit save on the (unsaved) `LoanApplication` and no shadow-
scoring `PredictionLog` row. Task 4 adds the `AdhocScoreView` tests that
drive the same dry-run path through the REST endpoint.
"""

from __future__ import annotations

import pytest

from apps.loans.models import LoanApplication
from apps.ml_engine.models import PredictionLog
from apps.ml_engine.services.governance.shadow_scoring import score_challengers_shadow
from apps.ml_engine.services.scoring import predictor as predictor_mod
from apps.ml_engine.services.scoring.policy_overlay import apply_policy_overlay
from apps.ml_engine.tests.predictor_stub import build_stub_predictor

pytestmark = pytest.mark.django_db


class TestPredictorDryRun:
    def test_persist_false_writes_nothing(self, monkeypatch):
        predictor = build_stub_predictor(
            monkeypatch,
            features={"purpose": "personal", "employment_type": "payg_permanent", "loan_amount": 20000},
            probability=0.4,
            threshold=0.5,
        )
        # Swap in the REAL write-site helpers (the stub no-ops them out) so
        # this test actually exercises — and would fail on — a missing guard,
        # instead of passing regardless because the stub never calls them.
        monkeypatch.setattr(predictor_mod, "_apply_policy_overlay_helper", apply_policy_overlay)
        monkeypatch.setattr(predictor_mod, "_score_challengers_shadow_helper", score_challengers_shadow)

        app = LoanApplication(
            annual_income=60000,
            credit_score=680,
            loan_amount=20000,
            debt_to_income=3,
            employment_length=4,
            purpose="personal",
            home_ownership="rent",
            num_hardship_flags=1,  # P11 refer — exercises the referral-audit save guard
        )

        def _fail_if_saved(*_a, **_k):
            pytest.fail("persist=False must not save the unsaved LoanApplication")

        monkeypatch.setattr(app, "save", _fail_if_saved)

        result = predictor.predict(app, persist=False)

        assert "probability" in result
        assert LoanApplication.objects.count() == 0
        assert PredictionLog.objects.count() == 0
