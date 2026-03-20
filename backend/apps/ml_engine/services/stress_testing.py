"""Portfolio-level stress testing for the loan book.

Runs batch stress tests across the entire portfolio:
- Interest rate shocks (+2%, +3%)
- Unemployment rises (+3%)
- Property price declines (-20%)
- Combined adverse scenario
"""

import logging
from decimal import Decimal

from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.models import PredictionLog

logger = logging.getLogger('ml_engine.stress_testing')


class PortfolioStressTester:
    """Batch stress test the loan book against adverse scenarios."""

    SCENARIOS = {
        'rate_shock_2pct': {
            'description': 'Interest rate increase of 2%',
            'rate_increase': 0.02,
            'income_reduction': 0.0,
            'property_decline': 0.0,
        },
        'rate_shock_3pct': {
            'description': 'Interest rate increase of 3%',
            'rate_increase': 0.03,
            'income_reduction': 0.0,
            'property_decline': 0.0,
        },
        'unemployment_rise': {
            'description': 'Unemployment rises 3% — income reduction for affected borrowers',
            'rate_increase': 0.0,
            'income_reduction': 0.15,
            'property_decline': 0.0,
        },
        'property_decline_20pct': {
            'description': 'Property prices decline 20%',
            'rate_increase': 0.0,
            'income_reduction': 0.0,
            'property_decline': 0.20,
        },
        'combined_adverse': {
            'description': 'Combined: +2% rates, -15% income, -20% property',
            'rate_increase': 0.02,
            'income_reduction': 0.15,
            'property_decline': 0.20,
        },
    }

    def run_stress_test(self, scenario_name=None):
        """Run stress tests on all approved loans. Returns results per scenario."""
        scenarios = {scenario_name: self.SCENARIOS[scenario_name]} if scenario_name else self.SCENARIOS

        approved_apps = LoanApplication.objects.filter(
            status='approved',
        ).select_related('decision')

        total_approved = approved_apps.count()
        if total_approved == 0:
            return {'error': 'No approved loans to stress test'}

        results = {}
        for name, scenario in scenarios.items():
            at_risk = 0
            total_exposure = Decimal('0')
            at_risk_exposure = Decimal('0')

            for app in approved_apps.iterator(chunk_size=200):
                stressed = self._apply_scenario(app, scenario)
                total_exposure += app.loan_amount

                if stressed['would_default']:
                    at_risk += 1
                    at_risk_exposure += app.loan_amount

            results[name] = {
                'description': scenario['description'],
                'total_loans': total_approved,
                'at_risk_count': at_risk,
                'at_risk_pct': round(at_risk / total_approved * 100, 2) if total_approved else 0,
                'total_exposure': float(total_exposure),
                'at_risk_exposure': float(at_risk_exposure),
                'at_risk_exposure_pct': round(
                    float(at_risk_exposure / total_exposure * 100), 2
                ) if total_exposure else 0,
            }

            logger.info(
                'Stress test [%s]: %d/%d loans at risk (%.1f%% of exposure)',
                name, at_risk, total_approved, results[name]['at_risk_exposure_pct'],
            )

        return results

    def _apply_scenario(self, app, scenario):
        """Apply stress scenario to a single loan and check if it would default."""
        annual_income = float(app.annual_income) * (1 - scenario['income_reduction'])
        monthly_income = annual_income / 12

        # Stressed monthly repayment (rough P&I calculation)
        base_rate = 0.065  # assumed current rate
        stressed_rate = base_rate + scenario['rate_increase']
        monthly_rate = stressed_rate / 12
        term = app.loan_term_months
        loan = float(app.loan_amount)

        if monthly_rate > 0 and term > 0:
            payment = loan * monthly_rate * (1 + monthly_rate) ** term / ((1 + monthly_rate) ** term - 1)
        else:
            payment = loan / max(term, 1)

        # Estimate expenses at 35% of income
        expenses = monthly_income * 0.35
        surplus = monthly_income - expenses - payment

        # Check LVR under property decline
        property_value = float(app.property_value or 0)
        if property_value > 0:
            stressed_property = property_value * (1 - scenario['property_decline'])
            stressed_lvr = loan / stressed_property
        else:
            stressed_lvr = 0

        would_default = surplus < 0 or stressed_lvr > 1.0

        return {
            'would_default': would_default,
            'surplus': surplus,
            'stressed_lvr': stressed_lvr,
        }
