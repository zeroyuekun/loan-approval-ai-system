"""Management command for independent model validation (SR 11-7).

Compares the active (champion) model against one or more challenger models
on a holdout dataset, generates fairness metrics, and produces a
ModelValidationReport record ready for sign-off.

Usage:
    # Compare active model against all inactive models on holdout data
    python manage.py validate_model --data .tmp/synthetic_loans.csv

    # Compare specific challenger
    python manage.py validate_model --data .tmp/synthetic_loans.csv --challenger <uuid>

    # Record validator identity
    python manage.py validate_model --data .tmp/synthetic_loans.csv \\
        --validator "Jane Smith" --role "Risk Manager"
"""

import logging
from datetime import date

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import ModelValidationReport, ModelVersion

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run independent model validation: champion vs challenger comparison"

    def add_arguments(self, parser):
        parser.add_argument(
            "--data",
            required=True,
            help="Path to holdout CSV dataset for validation",
        )
        parser.add_argument(
            "--challenger",
            type=str,
            default=None,
            help="UUID of a specific challenger ModelVersion (default: all inactive)",
        )
        parser.add_argument(
            "--validator",
            type=str,
            default="System (automated)",
            help="Name of the validator performing this review",
        )
        parser.add_argument(
            "--role",
            type=str,
            default="Automated Validation Pipeline",
            help="Role of the validator",
        )

    def handle(self, *args, **options):

        data_path = options["data"]
        validator_name = options["validator"]
        validator_role = options["role"]

        # Load holdout data
        try:
            df = pd.read_csv(data_path)
        except FileNotFoundError as err:
            raise CommandError(f"Data file not found: {data_path}") from err

        if "approved" not in df.columns:
            raise CommandError('Dataset must contain an "approved" column as the target')

        self.stdout.write(f"Loaded holdout dataset: {len(df)} samples")

        # Get champion model
        champion = ModelVersion.objects.filter(is_active=True).first()
        if not champion:
            raise CommandError("No active (champion) model found")

        self.stdout.write(f"Champion: {champion}")

        # Get challenger(s)
        if options["challenger"]:
            challengers = ModelVersion.objects.filter(pk=options["challenger"])
            if not challengers.exists():
                raise CommandError(f"Challenger model not found: {options['challenger']}")
        else:
            challengers = (
                ModelVersion.objects.filter(
                    is_active=False,
                    retired_at__isnull=True,
                )
                .exclude(pk=champion.pk)
                .order_by("-created_at")[:3]
            )

        if not challengers.exists():
            self.stdout.write(self.style.WARNING("No challenger models found — running champion-only validation"))

        # Evaluate champion on holdout
        champion_metrics = self._evaluate_model(champion, df)
        self.stdout.write(f"Champion AUC: {champion_metrics['auc_roc']:.4f}")

        # Evaluate challengers
        comparison = {
            "champion": {
                "model_version": str(champion.id),
                "algorithm": champion.algorithm,
                "version": champion.version,
                **champion_metrics,
            }
        }

        for challenger in challengers:
            try:
                challenger_metrics = self._evaluate_model(challenger, df)
                comparison[f"challenger_{challenger.version}"] = {
                    "model_version": str(challenger.id),
                    "algorithm": challenger.algorithm,
                    "version": challenger.version,
                    **challenger_metrics,
                }
                delta_auc = challenger_metrics["auc_roc"] - champion_metrics["auc_roc"]
                self.stdout.write(
                    f"Challenger {challenger.version} AUC: "
                    f"{challenger_metrics['auc_roc']:.4f} (delta: {delta_auc:+.4f})"
                )
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Could not evaluate challenger {challenger.version}: {e}"))

        # Fairness review on champion
        fairness = self._evaluate_fairness(champion, df)

        # Determine outcome
        findings_parts = []
        findings_parts.append(f"Champion model (v{champion.version}) evaluated on {len(df)} holdout samples.")
        findings_parts.append(
            f"AUC-ROC: {champion_metrics['auc_roc']:.4f}, Brier: {champion_metrics.get('brier_score', 'N/A')}"
        )

        any_challenger_better = False
        for key, metrics in comparison.items():
            if key.startswith("challenger_"):
                if metrics["auc_roc"] > champion_metrics["auc_roc"] + 0.005:
                    any_challenger_better = True
                    findings_parts.append(
                        f"ALERT: Challenger {metrics['version']} outperforms champion "
                        f"by {metrics['auc_roc'] - champion_metrics['auc_roc']:.4f} AUC"
                    )

        fairness_issues = []
        for attr, data in fairness.items():
            if isinstance(data, dict) and data.get("disparate_impact_ratio", 1.0) < 0.80:
                fairness_issues.append(f"{attr}: DI ratio = {data['disparate_impact_ratio']:.3f}")

        if fairness_issues:
            findings_parts.append(
                f"FAIRNESS CONCERN: {len(fairness_issues)} attribute(s) below 80% DI threshold: "
                + ", ".join(fairness_issues)
            )

        if any_challenger_better:
            outcome = ModelValidationReport.Outcome.CONDITIONAL
            conditions = "Challenger model shows improvement — recommend A/B test before full rollout."
        elif fairness_issues:
            outcome = ModelValidationReport.Outcome.CONDITIONAL
            conditions = "Fairness concerns identified — require bias mitigation before continued use."
        else:
            outcome = ModelValidationReport.Outcome.APPROVED
            conditions = ""

        findings = "\n".join(findings_parts)

        # Create the report
        report = ModelValidationReport.objects.create(
            model_version=champion,
            validator_name=validator_name,
            validator_role=validator_role,
            validation_date=date.today(),
            outcome=outcome,
            methodology=(
                "Holdout evaluation on out-of-sample data with champion/challenger "
                "comparison and disparate impact fairness analysis across protected "
                "attributes (gender, age_group, state)."
            ),
            findings=findings,
            conditions=conditions,
            challenger_comparison=comparison,
            holdout_metrics=champion_metrics,
            fairness_review=fairness,
            next_validation_due=date(
                date.today().year + (1 if date.today().month <= 6 else 0),
                date.today().month + 6 if date.today().month <= 6 else date.today().month - 6,
                1,
            ),
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nValidation report created: {report.id}\n"
                f"Outcome: {report.get_outcome_display()}\n"
                f"Findings:\n{findings}"
            )
        )

        return str(report.id)

    def _evaluate_model(self, model_version, df):
        """Evaluate a model version on holdout data and return metrics."""
        import joblib
        from sklearn.metrics import (
            accuracy_score,
            brier_score_loss,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )

        model = joblib.load(model_version.file_path)

        # Get feature columns (exclude target and non-feature columns)
        exclude_cols = {"approved", "applicant_name", "id", "application_id"}
        feature_cols = [c for c in df.columns if c not in exclude_cols]

        X = df[feature_cols].select_dtypes(include=[np.number])
        y = df["approved"].values

        # Predict
        probabilities = model.predict_proba(X)[:, 1]
        threshold = model_version.optimal_threshold or 0.5
        predictions = (probabilities >= threshold).astype(int)

        return {
            "accuracy": round(float(accuracy_score(y, predictions)), 4),
            "precision": round(float(precision_score(y, predictions, zero_division=0)), 4),
            "recall": round(float(recall_score(y, predictions, zero_division=0)), 4),
            "f1_score": round(float(f1_score(y, predictions, zero_division=0)), 4),
            "auc_roc": round(float(roc_auc_score(y, probabilities)), 4),
            "brier_score": round(float(brier_score_loss(y, probabilities)), 4),
            "n_samples": len(y),
            "approval_rate": round(float(predictions.mean()), 4),
        }

    def _evaluate_fairness(self, model_version, df):
        """Run disparate impact analysis on protected attributes."""
        import joblib

        model = joblib.load(model_version.file_path)
        exclude_cols = {"approved", "applicant_name", "id", "application_id"}
        feature_cols = [c for c in df.columns if c not in exclude_cols]
        X = df[feature_cols].select_dtypes(include=[np.number])

        threshold = model_version.optimal_threshold or 0.5
        probabilities = model.predict_proba(X)[:, 1]
        predictions = (probabilities >= threshold).astype(int)

        fairness = {}
        protected_attrs = {
            "gender": df.get("gender"),
            "age_group": df.get("age_group") if "age_group" in df.columns else None,
            "state": df.get("state") if "state" in df.columns else None,
        }

        for attr, values in protected_attrs.items():
            if values is None:
                continue

            groups = values.unique()
            if len(groups) < 2:
                continue

            approval_rates = {}
            for g in groups:
                mask = values == g
                if mask.sum() > 0:
                    approval_rates[str(g)] = float(predictions[mask].mean())

            if approval_rates:
                max_rate = max(approval_rates.values())
                min_rate = min(approval_rates.values())
                di_ratio = min_rate / max_rate if max_rate > 0 else 0.0

                fairness[attr] = {
                    "approval_rates": approval_rates,
                    "disparate_impact_ratio": round(di_ratio, 4),
                    "passes_80_percent_rule": di_ratio >= 0.80,
                }

        return fairness
