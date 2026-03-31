from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0015_add_fraudcheck"),
    ]

    operations = [
        migrations.AlterField(
            model_name="loanapplication",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("approved", "Approved"),
                    ("conditional", "Conditionally Approved"),
                    ("denied", "Denied"),
                    ("review", "Under Review"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="loanapplication",
            name="conditions",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of condition dicts for conditional approvals",
            ),
        ),
        migrations.AddField(
            model_name="loanapplication",
            name="conditions_met",
            field=models.BooleanField(
                default=False,
                help_text="Whether all conditions have been satisfied",
            ),
        ),
    ]
