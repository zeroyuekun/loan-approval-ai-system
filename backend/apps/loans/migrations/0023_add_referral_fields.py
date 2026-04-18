"""D6 — referral audit trail fields on LoanApplication.

Populated by ModelPredictor.predict() when the credit-policy overlay's
refer rules (P08-P12) trigger. Admin-only surface via
`/api/loans/referrals/`; intentionally does not touch the bias review
queue (bias_reports__flagged=True remains the canonical bias filter).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0022_alter_loanapplication_status_pipelinedispatchoutbox"),
    ]

    operations = [
        migrations.AddField(
            model_name="loanapplication",
            name="referral_status",
            field=models.CharField(
                choices=[
                    ("none", "Not referred"),
                    ("referred", "Referred to underwriter"),
                    ("cleared", "Cleared by underwriter"),
                    ("escalated", "Escalated (further review)"),
                ],
                db_index=True,
                default="none",
                help_text="Referral state from credit-policy overlay (P08–P12); admin-only workflow.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="loanapplication",
            name="referral_codes",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Policy codes (e.g. ['P09', 'P11']) that triggered referral.",
            ),
        ),
        migrations.AddField(
            model_name="loanapplication",
            name="referral_rationale",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Code → human-readable reason map, captured at decision time for audit.",
            ),
        ),
    ]
