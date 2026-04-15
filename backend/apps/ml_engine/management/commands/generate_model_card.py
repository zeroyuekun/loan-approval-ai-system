# backend/apps/ml_engine/management/commands/generate_model_card.py
from __future__ import annotations

import json
import pathlib
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import ModelVersion

# Template is anchored relative to the Django BASE_DIR so the command works
# regardless of the caller's working directory.
INTENDED_USE_TEMPLATE = (
    pathlib.Path(settings.BASE_DIR).parent / "docs" / "model-cards" / "_template-intended-use.md"
)


class Command(BaseCommand):
    help = "Generate a Google-format Model Card markdown file from a ModelVersion row."

    def add_arguments(self, parser: Any) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        # Note: we use --version-id (not --version) because Django's BaseCommand
        # already reserves --version for its own version-printing behaviour.
        group.add_argument(
            "--version-id",
            dest="version_id",
            help="ModelVersion UUID",
        )
        group.add_argument("--active", action="store_true", help="Use the active model")
        parser.add_argument(
            "--output",
            default=None,
            help="Output path (default: docs/model-cards/<version>.md)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["active"]:
            mv = ModelVersion.objects.filter(is_active=True).order_by("-created_at").first()
            if mv is None:
                raise CommandError("No active ModelVersion found.")
        else:
            version_id = options["version_id"]
            try:
                mv = ModelVersion.objects.get(pk=version_id)
            except ModelVersion.DoesNotExist as exc:
                raise CommandError(f"ModelVersion {version_id} not found") from exc

        # Sanitize version for Windows-safe filenames (no : / \).
        safe_version = _sanitize_filename(mv.version)
        output = pathlib.Path(
            options["output"] or f"docs/model-cards/{safe_version}.md"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self._render(mv), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {output}"))

    def _render(self, mv: ModelVersion) -> str:
        intended_use = (
            INTENDED_USE_TEMPLATE.read_text(encoding="utf-8")
            if INTENDED_USE_TEMPLATE.exists()
            else "## Intended Use\n\n_Template file missing._\n\n## Factors\n\n_Template file missing._\n"
        )

        fairness_body = self._format_fairness(mv)
        metrics_body = self._format_metrics(mv)
        training_body = self._format_training(mv)

        return (
            f"# Model Card - {mv.algorithm.upper()} {mv.version}\n"
            f"\n"
            f"_Generated from `ModelVersion {mv.pk}` on {mv.created_at:%Y-%m-%d}_\n"
            f"\n"
            f"## Model Details\n"
            f"\n"
            f"- **Algorithm:** {mv.algorithm}\n"
            f"- **Version:** {mv.version}\n"
            f"- **Is active:** {mv.is_active}\n"
            f"- **Traffic percentage:** {mv.traffic_percentage}\n"
            f"- **File path (not user-facing):** `{mv.file_path}`\n"
            f"- **Created:** {mv.created_at:%Y-%m-%d}\n"
            f"\n"
            f"{intended_use}\n"
            f"\n"
            f"## Metrics\n"
            f"\n"
            f"{metrics_body}\n"
            f"\n"
            f"## Evaluation Data\n"
            f"\n"
            f"- **Test set source:** held-out split from the synthetic generator\n"
            f"- **Split strategy:** temporal (if `application_quarter` available) else stratified random 70/15/15\n"
            f"\n"
            f"## Training Data\n"
            f"\n"
            f"{training_body}\n"
            f"\n"
            f"## Quantitative Analyses\n"
            f"\n"
            f"{fairness_body}\n"
            f"\n"
            f"## Ethical Considerations\n"
            f"\n"
            f"- Decisions materially affect people; we require officer review for all escalated and declined cases.\n"
            f"- Protected attributes are not features; proxies are constrained via SA3 aggregation and monotonic constraints.\n"
            f"- Synthetic training data means real-world calibration on launch is unverified; shadow-mode recommended.\n"
            f"\n"
            f"## Caveats and Recommendations\n"
            f"\n"
            f"- Retrain when macro conditions change materially (RBA cash rate move >100bp, unemployment >1pp shift).\n"
            f"- Monitor PSI on key features; retrain if PSI > 0.2 on any top-10 feature.\n"
            f"- This card auto-generates from the ModelVersion row - fairness gaps reflect what has been computed, not what is possible.\n"
        )

    def _format_metrics(self, mv: ModelVersion) -> str:
        rows = [
            ("AUC-ROC", mv.auc_roc),
            ("Accuracy", mv.accuracy),
            ("Precision", mv.precision),
            ("Recall", mv.recall),
            ("F1", mv.f1_score),
            ("Brier score", mv.brier_score),
            ("Gini", mv.gini_coefficient),
            ("KS", mv.ks_statistic),
            ("ECE", mv.ece),
            ("Optimal threshold", mv.optimal_threshold),
        ]
        lines = ["| Metric | Value |", "|---|---|"]
        for name, value in rows:
            formatted = "-" if value is None else f"{value:.4f}"
            lines.append(f"| {name} | {formatted} |")
        if mv.confusion_matrix:
            lines.append("")
            lines.append("**Confusion matrix at optimal threshold:**")
            lines.append(f"```json\n{json.dumps(mv.confusion_matrix, indent=2)}\n```")
        if mv.calibration_data:
            method = mv.calibration_data.get("method", "unknown")
            lines.append("")
            lines.append(f"**Calibration method:** {method}")
        return "\n".join(lines)

    def _format_training(self, mv: ModelVersion) -> str:
        meta = mv.training_metadata or {}
        params = mv.training_params or {}
        lines: list[str] = []
        if meta:
            lines.append("**Training metadata:**")
            lines.append(f"```json\n{json.dumps(meta, indent=2, default=str)}\n```")
        if params:
            lines.append("")
            lines.append("**Training parameters:**")
            lines.append(f"```json\n{json.dumps(params, indent=2, default=str)}\n```")
        if not lines:
            lines.append("_No training metadata recorded on this version._")
        return "\n".join(lines)

    def _format_fairness(self, mv: ModelVersion) -> str:
        fm = mv.fairness_metrics or {}
        if not fm:
            return (
                "Subgroup fairness metrics not yet computed for this version. "
                "Subgroup AUC monitoring is on the Track C roadmap - see "
                "`docs/superpowers/specs/2026-04-15-portfolio-polish-design.md` "
                "out-of-scope items."
            )
        rendered = ["**Fairness metrics (recorded at training):**"]
        rendered.append(f"```json\n{json.dumps(fm, indent=2, default=str)}\n```")
        return "\n".join(rendered)


def _sanitize_filename(name: str) -> str:
    """Replace Windows-invalid filename characters with hyphens."""
    invalid = '<>:"/\\|?*'
    result = name
    for ch in invalid:
        result = result.replace(ch, "-")
    return result
