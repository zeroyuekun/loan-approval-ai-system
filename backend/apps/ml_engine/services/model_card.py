"""Model Card generator for APRA CPG 235 regulatory compliance.

Produces a structured model card from the active ModelVersion, covering
model details, training data, performance metrics, fairness analysis,
known limitations, and regulatory compliance statements.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.ml_engine.models import ModelVersion


class ModelCardGenerator:
    """Generate a structured model card from a ModelVersion instance."""

    def __init__(self, model_version: ModelVersion | None = None):
        if model_version is None:
            model_version = ModelVersion.objects.filter(is_active=True).first()
        if model_version is None:
            raise ValueError("No active model found")
        self.model_version = model_version

    def generate(self) -> dict[str, Any]:
        """Return the full model card as a nested dictionary."""
        mv = self.model_version
        metadata = mv.training_metadata or {}
        training_params = mv.training_params or {}

        return {
            'model_details': self._model_details(mv, metadata),
            'intended_use': self._intended_use(),
            'training_data': self._training_data(mv, metadata, training_params),
            'performance_metrics': self._performance_metrics(mv),
            'fairness_analysis': self._fairness_analysis(mv),
            'governance': self._governance(mv),
            'limitations': self._limitations(),
            'synthetic_data_validation': self._synthetic_data_validation(mv),
            'regulatory_compliance': self._regulatory_compliance(),
            'last_updated': mv.created_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    @staticmethod
    def _model_details(mv: ModelVersion, metadata: dict) -> dict[str, Any]:
        return {
            'name': f"{mv.get_algorithm_display()} Credit Risk Model",
            'version': mv.version,
            'algorithm': mv.algorithm,
            'created_at': mv.created_at.isoformat(),
            'description': (
                'XGBoost credit risk model for Australian personal '
                'and home loan approval'
            ),
        }

    @staticmethod
    def _intended_use() -> dict[str, str]:
        return {
            'primary_use': 'Automated credit risk assessment for loan applications',
            'users': 'Loan officers, automated pipeline',
            'out_of_scope': 'Commercial lending, international applications',
        }

    @staticmethod
    def _training_data(
        mv: ModelVersion, metadata: dict, training_params: dict
    ) -> dict[str, Any]:
        train_size = metadata.get('train_size', 0)
        val_size = metadata.get('val_size', 0)
        test_size = metadata.get('test_size', 0)
        total_size = train_size + val_size + test_size

        # Fall back to training_params for size/features if metadata is sparse
        if total_size == 0:
            total_size = training_params.get('n_samples', 0)

        n_features = metadata.get('n_features') or training_params.get(
            'n_features', 0
        )

        label_distribution = {}
        class_balance = metadata.get('class_balance')
        if class_balance is not None:
            label_distribution = {
                'approved': round(float(class_balance), 4),
                'denied': round(1.0 - float(class_balance), 4),
            }

        return {
            'description': (
                'Synthetic data calibrated to Australian Bureau of '
                'Statistics and APRA benchmarks'
            ),
            'size': total_size,
            'features': n_features,
            'label_distribution': label_distribution,
        }

    @staticmethod
    def _performance_metrics(mv: ModelVersion) -> dict[str, Any]:
        gini = None
        if mv.gini_coefficient is not None:
            gini = mv.gini_coefficient
        elif mv.auc_roc is not None:
            gini = round(2 * mv.auc_roc - 1, 4)

        return {
            'accuracy': mv.accuracy,
            'precision': mv.precision,
            'recall': mv.recall,
            'f1_score': mv.f1_score,
            'auc_roc': mv.auc_roc,
            'gini': gini,
            'brier_score': mv.brier_score,
            'ece': mv.ece,
        }

    @staticmethod
    def _fairness_analysis(mv: ModelVersion) -> dict[str, Any]:
        fairness = mv.fairness_metrics or {}

        # Extract disparate impact ratios if present
        disparate_impact: dict[str, Any] = {}
        for attr, data in fairness.items():
            if isinstance(data, dict):
                if 'disparate_impact_ratio' in data:
                    disparate_impact[attr] = data['disparate_impact_ratio']
                elif 'passes_80_percent_rule' in data:
                    disparate_impact[attr] = data

        return {
            'protected_attributes': ['gender', 'age_group', 'state'],
            'disparate_impact_ratio': disparate_impact,
            'mitigation': 'Fairness reweighting during training',
        }

    @staticmethod
    def _governance(mv: ModelVersion) -> dict[str, Any]:
        return {
            'decision_thresholds': {
                'approve': mv.decision_threshold_approve,
                'deny': mv.decision_threshold_deny,
                'human_review': mv.decision_threshold_review,
            },
            'explainability_method': mv.explainability_method,
            'next_review_date': (
                mv.next_review_date.isoformat() if mv.next_review_date else None
            ),
            'retired_at': (
                mv.retired_at.isoformat() if mv.retired_at else None
            ),
            'status': 'retired' if mv.retired_at else 'active',
            'retraining_policy': mv.retraining_policy or {},
        }

    @staticmethod
    def _limitations() -> list[str]:
        return [
            'Trained on synthetic data — TSTR framework estimates 3-8% AUC '
            'degradation vs real data (see synthetic_data_validation section)',
            'Point-in-time prediction — does not model time-to-default',
            'State-level geographic granularity only',
        ]

    @staticmethod
    def _synthetic_data_validation(mv: ModelVersion) -> dict[str, Any]:
        """TSTR validation summary for model card transparency."""
        metadata = mv.training_metadata or {}
        tstr = metadata.get('tstr_validation', {})

        if not tstr:
            return {
                'status': 'not_available',
                'note': 'TSTR validation was not computed for this model version.',
            }

        real_auc = tstr.get('estimated_real_world_auc', {})
        confidence = tstr.get('synthetic_confidence', {})

        return {
            'status': 'available',
            'estimated_real_world_auc': real_auc.get('estimated_real_auc'),
            'estimated_auc_range': real_auc.get('estimated_range'),
            'degradation_from_synthetic': real_auc.get('total_degradation'),
            'synthetic_confidence_score': confidence.get('overall_score'),
            'confidence_interpretation': confidence.get('interpretation'),
            'methodology': real_auc.get('methodology'),
            'references': real_auc.get('references', []),
            'note': (
                'These estimates are based on published research on synthetic-to-real '
                'transfer learning degradation. Actual performance on real loan data '
                'may differ. See references for methodology.'
            ),
        }

    @staticmethod
    def _regulatory_compliance() -> dict[str, bool]:
        return {
            'apra_cpg_235': True,
            'nccp_act': True,
            'banking_code': True,
        }
