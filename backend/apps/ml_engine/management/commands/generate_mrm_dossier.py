"""Management command: generate an MRM dossier for a ModelVersion.

Usage:
    python manage.py generate_mrm_dossier <model_version_id>
    python manage.py generate_mrm_dossier <model_version_id> --output-dir models/

The dossier is written to `<output_dir>/<model_version_id>/mrm.md` and
the path is printed to stdout. Delegates to the pure-functional
`services.mrm_dossier.generate_dossier_markdown` so the formatting is
identical across CLI and Celery auto-generation paths.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.mrm_dossier import write_dossier


class Command(BaseCommand):
    help = "Generate a Model Risk Management dossier for a specific ModelVersion"

    def add_arguments(self, parser):
        parser.add_argument(
            "model_version_id",
            type=str,
            help="UUID of the ModelVersion to document",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Root directory for generated dossier (default: settings.ML_MODELS_DIR)",
        )

    def handle(self, *args, **options):
        model_id = options["model_version_id"]
        output_dir = options["output_dir"] or str(settings.ML_MODELS_DIR)

        try:
            mv = ModelVersion.objects.get(pk=model_id)
        except ModelVersion.DoesNotExist as err:
            raise CommandError(f"ModelVersion not found: {model_id}") from err

        path = write_dossier(mv, output_dir)
        self.stdout.write(self.style.SUCCESS(f"Dossier written: {path}"))
        return path
