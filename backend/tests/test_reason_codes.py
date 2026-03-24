"""Tests for adverse action reason codes and reapplication guidance — pure Python, no DB."""

import pytest

from apps.ml_engine.services.reason_codes import (
    REASON_CODE_MAP,
    generate_adverse_action_reasons,
    generate_reapplication_guidance,
)


# ------------------------------------------------------------------
# generate_adverse_action_reasons
# ------------------------------------------------------------------

class TestAdverseActionReasons:
    def test_approved_returns_empty(self):
        shap = {'credit_score': -0.3, 'annual_income': -0.2}
        assert generate_adverse_action_reasons(shap, 'approved') == []

    def test_empty_shap_returns_empty(self):
        assert generate_adverse_action_reasons({}, 'denied') == []

    def test_denied_returns_reasons_sorted_by_most_negative(self):
        shap = {
            'annual_income': -0.1,
            'credit_score': -0.5,
            'debt_to_income': -0.3,
        }
        reasons = generate_adverse_action_reasons(shap, 'denied')
        assert len(reasons) == 3
        assert reasons[0]['code'] == 'R06'  # credit_score is most negative
        assert reasons[1]['code'] == 'R03'  # debt_to_income
        assert reasons[2]['code'] == 'R01'  # annual_income

    def test_max_reasons_limits_output(self):
        shap = {
            'annual_income': -0.1,
            'credit_score': -0.5,
            'debt_to_income': -0.3,
            'loan_amount': -0.2,
            'employment_length': -0.15,
        }
        reasons = generate_adverse_action_reasons(shap, 'denied', max_reasons=2)
        assert len(reasons) == 2

    def test_positive_shap_values_excluded(self):
        shap = {
            'credit_score': -0.5,
            'annual_income': 0.3,  # positive, should be excluded
        }
        reasons = generate_adverse_action_reasons(shap, 'denied')
        assert len(reasons) == 1
        assert reasons[0]['feature'] == 'credit_score'

    def test_unknown_features_skipped(self):
        shap = {
            'totally_unknown_feature': -0.9,
            'credit_score': -0.2,
        }
        reasons = generate_adverse_action_reasons(shap, 'denied')
        assert len(reasons) == 1
        assert reasons[0]['code'] == 'R06'

    def test_deduplication_by_reason_code(self):
        """Multiple employment_type features map to R11; only the first should appear."""
        shap = {
            'employment_type_payg_casual': -0.4,
            'employment_type_self_employed': -0.3,
            'employment_type_contract': -0.2,
            'credit_score': -0.1,
        }
        reasons = generate_adverse_action_reasons(shap, 'denied')
        r11_count = sum(1 for r in reasons if r['code'] == 'R11')
        assert r11_count == 1
        # Should still include credit_score
        assert any(r['code'] == 'R06' for r in reasons)

    def test_result_dict_structure(self):
        shap = {'credit_score': -0.1234}
        reasons = generate_adverse_action_reasons(shap, 'denied')
        assert len(reasons) == 1
        r = reasons[0]
        assert r['code'] == 'R06'
        assert r['reason'] == 'Credit score below minimum lending threshold'
        assert r['feature'] == 'credit_score'
        assert r['contribution'] == -0.1234

    def test_contribution_rounded_to_4_decimals(self):
        shap = {'annual_income': -0.123456789}
        reasons = generate_adverse_action_reasons(shap, 'denied')
        assert reasons[0]['contribution'] == -0.1235


# ------------------------------------------------------------------
# generate_reapplication_guidance
# ------------------------------------------------------------------

class TestReapplicationGuidance:
    def test_bankruptcy_sets_24_months(self):
        reasons = [{'code': 'R08'}]
        result = generate_reapplication_guidance([], reasons)
        assert result['estimated_review_months'] == 24

    def test_employment_sets_12_months(self):
        reasons = [{'code': 'R09'}]
        result = generate_reapplication_guidance([], reasons)
        assert result['estimated_review_months'] == 12

    def test_credit_score_sets_6_months(self):
        reasons = [{'code': 'R06'}]
        result = generate_reapplication_guidance([], reasons)
        assert result['estimated_review_months'] == 6

    def test_debt_sets_6_months(self):
        reasons = [{'code': 'R03'}]
        result = generate_reapplication_guidance([], reasons)
        assert result['estimated_review_months'] == 6

    def test_expenses_sets_6_months(self):
        reasons = [{'code': 'R05'}]
        result = generate_reapplication_guidance([], reasons)
        assert result['estimated_review_months'] == 6

    def test_default_is_3_months(self):
        reasons = [{'code': 'R12'}]
        result = generate_reapplication_guidance([], reasons)
        assert result['estimated_review_months'] == 3

    def test_max_of_multiple_reason_timelines(self):
        """Bankruptcy (24) should win over credit score (6)."""
        reasons = [{'code': 'R06'}, {'code': 'R08'}, {'code': 'R03'}]
        result = generate_reapplication_guidance([], reasons)
        assert result['estimated_review_months'] == 24

    def test_counterfactuals_populate_targets(self):
        cfs = [
            {'feature': 'credit_score', 'current': 580, 'target': 650, 'description': 'Improve credit score'},
            {'feature': 'annual_income', 'current': 40000, 'target': 55000, 'description': 'Increase income'},
        ]
        result = generate_reapplication_guidance(cfs, [])
        assert len(result['improvement_targets']) == 2
        assert result['improvement_targets'][0]['feature'] == 'credit_score'
        assert result['improvement_targets'][1]['target_value'] == 55000

    def test_counterfactuals_limited_to_three(self):
        cfs = [{'feature': f'f{i}', 'current': i, 'target': i + 1, 'description': ''} for i in range(5)]
        result = generate_reapplication_guidance(cfs, [])
        assert len(result['improvement_targets']) == 3

    def test_message_includes_months(self):
        result = generate_reapplication_guidance([], [{'code': 'R09'}])
        assert '12 months' in result['message']

    def test_empty_inputs(self):
        result = generate_reapplication_guidance([], [])
        assert result['estimated_review_months'] == 3
        assert result['improvement_targets'] == []
        assert isinstance(result['message'], str)
