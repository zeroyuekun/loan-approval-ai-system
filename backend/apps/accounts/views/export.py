"""Customer data export view (Australian Privacy Act APP-12)."""

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.loans.models import AuditLog

from ..models import CustomerProfile
from ._shared import DataExportThrottle


class CustomerDataExportView(generics.GenericAPIView):
    """Export all customer data (APP 12 — Australian Privacy Act 1988)."""

    permission_classes = (IsAuthenticated,)
    throttle_classes = (DataExportThrottle,)

    def get(self, request):
        user = request.user
        data = {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": user.role,
                "created_at": user.created_at.isoformat(),
            },
        }

        # Profile data
        try:
            profile = user.profile
            data["profile"] = {
                f.name: str(getattr(profile, f.name, ""))
                for f in profile._meta.get_fields()
                if hasattr(f, "column") and f.name not in ("id", "user")
            }
        except CustomerProfile.DoesNotExist:
            data["profile"] = None

        # Loan applications with related decisions, emails, agent runs, bias reports
        from apps.loans.models import LoanApplication, LoanDecision

        applications = (
            LoanApplication.objects.filter(applicant=user)
            .select_related("decision", "decision__model_version")
            .prefetch_related(
                "emails",
                "agent_runs__bias_reports",
                "marketing_emails",
            )
        )

        apps_data = []
        for app in applications:
            app_dict = {
                "id": str(app.id),
                "loan_amount": str(app.loan_amount),
                "purpose": app.purpose,
                "status": app.status,
                "created_at": app.created_at.isoformat(),
            }

            # Loan decision with ML explanation
            try:
                d = app.decision
                app_dict["decision"] = {
                    "decision": d.decision,
                    "confidence": d.confidence,
                    "risk_grade": d.risk_grade,
                    "feature_importances": d.feature_importances,
                    "shap_values": d.shap_values,
                    "reasoning": d.reasoning,
                    "model_version": str(d.model_version) if d.model_version else None,
                    "created_at": d.created_at.isoformat(),
                }
            except LoanDecision.DoesNotExist:
                app_dict["decision"] = None

            # Generated emails (approval/denial)
            app_dict["emails"] = [
                {
                    "subject": e.subject,
                    "body": e.body,
                    "decision": e.decision,
                    "created_at": e.created_at.isoformat(),
                }
                for e in app.emails.all()
            ]

            # Marketing emails
            app_dict["marketing_emails"] = [
                {
                    "subject": me.subject,
                    "body": me.body,
                    "sent": me.sent,
                    "sent_at": me.sent_at.isoformat() if me.sent_at else None,
                    "created_at": me.created_at.isoformat(),
                }
                for me in app.marketing_emails.all()
            ]

            # Agent run summaries with bias reports
            app_dict["agent_runs"] = [
                {
                    "status": run.status,
                    "steps": run.steps,
                    "created_at": run.created_at.isoformat(),
                    "bias_reports": [
                        {
                            "bias_score": br.bias_score,
                            "categories": br.categories,
                            "analysis": br.analysis,
                            "flagged": br.flagged,
                            "created_at": br.created_at.isoformat(),
                        }
                        for br in run.bias_reports.all()
                    ],
                }
                for run in app.agent_runs.all()
            ]

            apps_data.append(app_dict)

        data["loan_applications"] = apps_data

        # Audit log entries
        audit_logs = (
            AuditLog.objects.filter(user=user)
            .order_by("-timestamp")[:100]
            .values(
                "action",
                "resource_type",
                "timestamp",
            )
        )
        data["audit_logs"] = [{k: str(v) for k, v in log.items()} for log in audit_logs]

        AuditLog.objects.create(
            user=user,
            action="data_export",
            resource_type="CustomUser",
            resource_id=str(user.id),
            details={},
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        return Response(data)
