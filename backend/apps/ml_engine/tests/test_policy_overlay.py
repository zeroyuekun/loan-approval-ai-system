"""Unit tests for the D3 policy-overlay + D6 referral-audit extraction.

`apply_policy_overlay` is the block carved out of `ModelPredictor.predict()`
during Arm C Phase 1. It:

- Calls `credit_policy.evaluate(application)` + `current_mode()` +
  `apply_overlay_to_decision()` to determine the post-overlay label.
- In shadow mode, emits a `credit_policy_shadow_disagreement` warning if the
  hypothetical enforce decision would have differed.
- Builds the `policy_payload` dict.
- In enforce mode + refer, sets `requires_human_review=True`.
- Persists D6 referral audit fields (`referral_status`, `referral_codes`,
  `referral_rationale`) on the `LoanApplication` if the policy referred.
- Fail-open on any exception: returns the unchanged label and an
  `{passed: None, mode: "off", error: ...}` payload.

Tests mock the `credit_policy` module functions rather than exercising real
rule evaluation — the overlay behaviour is already covered by
`test_credit_policy.py`. These tests cover the glue / branching logic only.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from apps.ml_engine.services.policy_overlay import apply_policy_overlay


class _FakeReferralStatus:
    REFERRED = "referred"


class _FakePolicyResult:
    """Matches the real PolicyResult dataclass surface used by the overlay path."""

    def __init__(self, *, passed=True, hard_fails=(), refers=(), rationale=None):
        self._passed = passed
        self.hard_fails = tuple(hard_fails)
        self.refers = tuple(refers)
        self.rationale_by_code = dict(rationale or {})

    @property
    def passed(self):
        return self._passed

    @property
    def has_refer(self):
        return bool(self.refers)

    def to_dict(self):
        return {
            "passed": self.passed,
            "hard_fails": list(self.hard_fails),
            "refers": list(self.refers),
            "rationale_by_code": dict(self.rationale_by_code),
        }


def _mk_application(*, with_referral_save=True):
    app = SimpleNamespace(
        id="app-123",
        referral_status=None,
        referral_codes=None,
        referral_rationale=None,
        ReferralStatus=_FakeReferralStatus,
    )
    if with_referral_save:
        app.save = MagicMock()
    return app


def _mk_model_version():
    return SimpleNamespace(id="mv-1")


def _patch_policy(*, evaluate_result, current_mode, apply_overlay_to_decision):
    """Patch the three credit_policy module functions the overlay helper calls."""
    return patch.multiple(
        "apps.ml_engine.services.policy_overlay._policy",
        evaluate=MagicMock(return_value=evaluate_result),
        current_mode=MagicMock(return_value=current_mode),
        apply_overlay_to_decision=MagicMock(side_effect=apply_overlay_to_decision),
        OVERLAY_MODE_SHADOW="shadow",
        OVERLAY_MODE_ENFORCE="enforce",
        OVERLAY_MODE_OFF="off",
    )


class TestApplyPolicyOverlay:
    def test_shadow_pass_leaves_label_and_review_flag_unchanged(self):
        app = _mk_application()
        mv = _mk_model_version()
        result = _FakePolicyResult(passed=True)

        with _patch_policy(
            evaluate_result=result,
            current_mode="shadow",
            apply_overlay_to_decision=lambda label, _r, _m: label,
        ):
            label, review, payload = apply_policy_overlay(
                application=app,
                model_version=mv,
                prediction_label="approved",
                requires_human_review=False,
            )

        assert label == "approved"
        assert review is False
        assert payload["passed"] is True
        assert payload["mode"] == "shadow"
        assert payload["changed_model_decision"] is False

    def test_enforce_hard_fail_flips_label_to_denied(self):
        app = _mk_application()
        mv = _mk_model_version()
        result = _FakePolicyResult(passed=False, hard_fails=("P01",))

        def _overlay(label, _r, mode):
            return "denied" if mode == "enforce" else label

        with _patch_policy(
            evaluate_result=result,
            current_mode="enforce",
            apply_overlay_to_decision=_overlay,
        ):
            label, review, payload = apply_policy_overlay(
                application=app,
                model_version=mv,
                prediction_label="approved",
                requires_human_review=False,
            )

        assert label == "denied"
        assert payload["changed_model_decision"] is True

    def test_enforce_refer_sets_requires_human_review(self):
        app = _mk_application()
        mv = _mk_model_version()
        result = _FakePolicyResult(passed=False, refers=("P08",))

        with _patch_policy(
            evaluate_result=result,
            current_mode="enforce",
            apply_overlay_to_decision=lambda label, _r, _m: label,
        ):
            label, review, _payload = apply_policy_overlay(
                application=app,
                model_version=mv,
                prediction_label="approved",
                requires_human_review=False,
            )

        assert review is True

    def test_shadow_mode_logs_disagreement_when_enforce_would_differ(self):
        app = _mk_application()
        mv = _mk_model_version()
        result = _FakePolicyResult(passed=False, hard_fails=("P03",))

        def _overlay(label, _r, mode):
            return "denied" if mode == "enforce" else label

        with _patch_policy(
            evaluate_result=result,
            current_mode="shadow",
            apply_overlay_to_decision=_overlay,
        ), patch("apps.ml_engine.services.policy_overlay.logger") as log:
            label, _review, _payload = apply_policy_overlay(
                application=app,
                model_version=mv,
                prediction_label="approved",
                requires_human_review=False,
            )

        # Shadow mode: label stays "approved"; disagreement logged.
        assert label == "approved"
        assert any(
            "credit_policy_shadow_disagreement" in str(call)
            for call in log.warning.call_args_list
        )

    def test_refer_persists_audit_fields_on_application(self):
        app = _mk_application()
        mv = _mk_model_version()
        result = _FakePolicyResult(
            passed=False,
            refers=("P08", "P10"),
            rationale={"P08": "LTI above threshold", "P10": "Self-employed <24mo"},
        )

        with _patch_policy(
            evaluate_result=result,
            current_mode="enforce",
            apply_overlay_to_decision=lambda label, _r, _m: label,
        ):
            apply_policy_overlay(
                application=app,
                model_version=mv,
                prediction_label="approved",
                requires_human_review=False,
            )

        assert app.referral_status == _FakeReferralStatus.REFERRED
        assert app.referral_codes == ["P08", "P10"]
        assert app.referral_rationale == {
            "P08": "LTI above threshold",
            "P10": "Self-employed <24mo",
        }
        app.save.assert_called_once_with(
            update_fields=["referral_status", "referral_codes", "referral_rationale"],
        )

    def test_audit_save_failure_is_swallowed(self):
        app = _mk_application()
        app.save = MagicMock(side_effect=RuntimeError("db down"))
        mv = _mk_model_version()
        result = _FakePolicyResult(passed=False, refers=("P08",))

        with _patch_policy(
            evaluate_result=result,
            current_mode="enforce",
            apply_overlay_to_decision=lambda label, _r, _m: label,
        ):
            # Must not raise.
            label, _review, _payload = apply_policy_overlay(
                application=app,
                model_version=mv,
                prediction_label="approved",
                requires_human_review=False,
            )

        assert label == "approved"

    def test_application_none_does_not_crash_audit_step(self):
        mv = _mk_model_version()
        result = _FakePolicyResult(passed=False, refers=("P08",))

        with _patch_policy(
            evaluate_result=result,
            current_mode="enforce",
            apply_overlay_to_decision=lambda label, _r, _m: label,
        ):
            # Must not raise even though application is None.
            label, _review, _payload = apply_policy_overlay(
                application=None,
                model_version=mv,
                prediction_label="approved",
                requires_human_review=False,
            )

        assert label == "approved"

    def test_outer_exception_returns_fail_open_payload(self):
        """If credit_policy.evaluate itself raises, overlay must not crash prediction."""
        app = _mk_application()
        mv = _mk_model_version()

        with patch(
            "apps.ml_engine.services.policy_overlay._policy.evaluate",
            side_effect=RuntimeError("policy engine broken"),
        ):
            label, review, payload = apply_policy_overlay(
                application=app,
                model_version=mv,
                prediction_label="approved",
                requires_human_review=False,
            )

        assert label == "approved"
        assert review is False
        assert payload["passed"] is None
        assert payload["mode"] == "off"
        assert "policy engine broken" in payload["error"]

    def test_shadow_refer_only_logs_if_hypothetical_differs(self):
        """Shadow-mode disagreement log must fire only when enforce would actually
        change the decision — not on every refer."""
        app = _mk_application()
        mv = _mk_model_version()
        result = _FakePolicyResult(passed=False, refers=("P08",))

        # Enforce-mode overlay returns the same label (refer doesn't flip approved).
        def _overlay(label, _r, _mode):
            return label

        with _patch_policy(
            evaluate_result=result,
            current_mode="shadow",
            apply_overlay_to_decision=_overlay,
        ), patch("apps.ml_engine.services.policy_overlay.logger") as log:
            apply_policy_overlay(
                application=app,
                model_version=mv,
                prediction_label="approved",
                requires_human_review=False,
            )

        assert not any(
            "credit_policy_shadow_disagreement" in str(call)
            for call in log.warning.call_args_list
        )
