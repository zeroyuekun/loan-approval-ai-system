from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0013_apicalllog_outcome"),
    ]

    operations = [
        migrations.AlterField(
            model_name="biasreport",
            name="score_source",
            field=models.CharField(default="composite", max_length=32),
        ),
    ]
