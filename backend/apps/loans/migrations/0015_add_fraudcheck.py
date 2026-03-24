import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0014_add_decision_waterfall'),
    ]

    operations = [
        migrations.CreateModel(
            name='FraudCheck',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('passed', models.BooleanField(help_text='True if no high-risk check failed')),
                ('risk_score', models.FloatField(help_text='Composite risk score 0-1')),
                ('checks', models.JSONField(default=list, help_text='List of individual check results')),
                ('flagged_reasons', models.JSONField(default=list, help_text='Human-readable reasons for failed checks')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fraud_checks', to='loans.loanapplication')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
