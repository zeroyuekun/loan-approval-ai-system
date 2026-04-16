# Generated migration for adding counterfactual_results field

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0020_protect_user_deletion"),
    ]

    operations = [
        migrations.AddField(
            model_name="loandecision",
            name="counterfactual_results",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="DiCE counterfactual explanations for denied applications",
            ),
        ),
    ]
