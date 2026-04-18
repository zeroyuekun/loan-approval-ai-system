# Generated for Arm A / D2 — Segmented model training (2026-04-18)

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ml_engine", "0008_add_validation_report"),
    ]

    operations = [
        migrations.AddField(
            model_name="modelversion",
            name="segment",
            field=models.CharField(
                choices=[
                    ("unified", "Unified (all products)"),
                    ("home_owner_occupier", "Home loans — owner-occupier"),
                    ("home_investor", "Home loans — investor"),
                    ("personal", "Personal loans"),
                ],
                default="unified",
                help_text=(
                    "Product segment this model was trained for. `unified` "
                    "is the fallback that scores all applications. "
                    "Per-segment models (home owner-occupier / home "
                    "investor / personal) are selected ahead of unified "
                    "when available and meet the minimum-sample threshold "
                    "— otherwise the predictor falls back to unified."
                ),
                max_length=40,
            ),
        ),
        migrations.AddIndex(
            model_name="modelversion",
            index=models.Index(
                fields=["segment", "is_active"],
                name="ml_modelver_segment_active_idx",
            ),
        ),
    ]
