"""Persist the validation-chosen threshold on models trained before the coherence fix.

Those rows stored Youden's J on the TEST split as optimal_threshold (the live
champion: 0.5) while the cost-optimal threshold chosen on the VALIDATION split
went to training_metadata.optimal_threshold (0.87) and anchored the
per-employment-type thresholds that actually served. Scoring now applies one
threshold to every applicant and ignores group thresholds, so without this
the live model would approve at the test-split 0.5. The previous value is kept
in training_metadata.superseded_optimal_threshold; the reverse restores it.
"""

from django.db import migrations


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def persist_validation_threshold(apps, schema_editor):
    ModelVersion = apps.get_model("ml_engine", "ModelVersion")
    for mv in ModelVersion.objects.all().only("pk", "optimal_threshold", "training_metadata"):
        meta = dict(mv.training_metadata or {})
        chosen = _number(meta.get("optimal_threshold"))
        if chosen is None or mv.optimal_threshold == chosen:
            continue
        meta["superseded_optimal_threshold"] = mv.optimal_threshold
        meta["decision_threshold"] = {
            "value": chosen,
            "applies_to": "all_applicants",
            "selected_on": "validation",
            "method": "cost_optimal",
        }
        ModelVersion.objects.filter(pk=mv.pk).update(optimal_threshold=chosen, training_metadata=meta)


def restore_superseded_threshold(apps, schema_editor):
    ModelVersion = apps.get_model("ml_engine", "ModelVersion")
    for mv in ModelVersion.objects.filter(training_metadata__has_key="superseded_optimal_threshold"):
        meta = dict(mv.training_metadata)
        previous = meta.pop("superseded_optimal_threshold")
        meta.pop("decision_threshold", None)
        ModelVersion.objects.filter(pk=mv.pk).update(optimal_threshold=previous, training_metadata=meta)


class Migration(migrations.Migration):
    dependencies = [
        ("ml_engine", "0009_modelversion_segment"),
    ]

    operations = [
        migrations.RunPython(persist_validation_threshold, restore_superseded_threshold),
    ]
