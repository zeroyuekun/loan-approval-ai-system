"""Compute the four operator status-strip sub-statuses for the dashboard
home (PR-2 of the dashboard persona refit).

Each function returns a dict with at least:
    {
        "level": "none" | "moderate" | "significant" | "unknown",
        "detail": "human-readable single line",
    }

`pending_review_status` adds `count`, `oldest_age_hours`, `sla_breach`.
`watchdog_status` adds `last_check` when available.

These are pure functions — no caching, no DRF — so they're trivial to
unit-test. The caller (DashboardStatsView) is responsible for
30s-caching the assembled payload.
"""

import logging

import redis
from django.conf import settings
from django.utils import timezone

from apps.agents.models import AgentRun
from apps.ml_engine.models import DriftReport, ModelVersion
from apps.ml_engine.services.governance.fairness_gate import check_fairness_gate

logger = logging.getLogger(__name__)

# Pending review SLA: any escalated AgentRun waiting longer than this is
# flagged as "significant" with sla_breach=True.
PENDING_REVIEW_SLA_HOURS = 24


def drift_status(active_model: ModelVersion | None) -> dict:
    """Latest DriftReport.alert_level for the active model."""
    if active_model is None:
        return {"level": "unknown", "detail": "No active model"}

    report = DriftReport.objects.filter(model_version=active_model).order_by("-report_date").first()
    if report is None:
        return {"level": "unknown", "detail": "No drift reports yet"}

    level_map = {"none": "none", "moderate": "moderate", "significant": "significant"}
    psi_str = f"PSI {report.psi_score:.2f}" if report.psi_score is not None else "PSI n/a"
    return {
        "level": level_map.get(report.alert_level, "unknown"),
        "detail": f"{psi_str} (report {report.report_date.isoformat()})",
    }


def fairness_status(active_model: ModelVersion | None) -> dict:
    """Re-evaluate the fairness gate against the active model's stored
    fairness_metrics. Treats the EEOC four-fifths threshold as the gate.

    Returns one of the unified StatusLevel values — "none" when the gate
    passes, "significant" when it fails, "unknown" when there is no
    active model or no fairness metrics recorded. This keeps the four
    indicators on a single vocabulary the frontend StatusStrip renders.
    """
    if active_model is None:
        return {"level": "unknown", "detail": "No active model"}

    fairness_metrics = active_model.fairness_metrics or {}
    if not fairness_metrics:
        return {"level": "unknown", "detail": "No fairness metrics recorded"}

    gate = check_fairness_gate(fairness_metrics)
    if gate["passed"]:
        min_dir = gate["minimum_dir"]
        detail = f"Min DIR {min_dir:.2f}" if min_dir is not None else "Pass"
        return {"level": "none", "detail": detail}
    else:
        failing = ", ".join(gate["failing_attributes"])
        return {"level": "significant", "detail": f"Failing: {failing}"}


def pending_review_status() -> dict:
    """Count escalated AgentRuns and report the oldest age. SLA breach
    when any pending is older than PENDING_REVIEW_SLA_HOURS.
    """
    now = timezone.now()
    pending_qs = AgentRun.objects.filter(status="escalated").order_by("created_at")
    count = pending_qs.count()

    if count == 0:
        return {
            "level": "none",
            "detail": "No pending reviews",
            "count": 0,
            "oldest_age_hours": None,
            "sla_breach": False,
        }

    oldest = pending_qs.first()
    age = now - oldest.created_at
    age_hours = round(age.total_seconds() / 3600, 1)
    sla_breach = age_hours >= PENDING_REVIEW_SLA_HOURS

    if sla_breach:
        return {
            "level": "significant",
            "detail": f"{count} pending; oldest {age_hours}h (SLA breached)",
            "count": count,
            "oldest_age_hours": age_hours,
            "sla_breach": True,
        }
    return {
        "level": "moderate",
        "detail": f"{count} pending; oldest {age_hours}h",
        "count": count,
        "oldest_age_hours": age_hours,
        "sla_breach": False,
    }


def watchdog_status() -> dict:
    """Read the `watchdog:health` Redis hash written by the watchdog
    management command. TTL is 120s — missing key means the watchdog
    hasn't run recently.
    """
    try:
        r = redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=3)
        raw = r.hgetall("watchdog:health")
    except Exception as exc:
        logger.warning("watchdog_status_redis_unreachable: %s", exc)
        return {"level": "unknown", "detail": "Redis unreachable"}

    if not raw:
        return {"level": "unknown", "detail": "Watchdog state stale (key expired)"}

    def _decode(v):
        return v.decode() if isinstance(v, (bytes, bytearray)) else v

    decoded = {_decode(k): _decode(v) for k, v in raw.items()}
    status = decoded.get("status", "unknown")
    failures = decoded.get("consecutive_failures", "0")
    last_check = decoded.get("last_check")

    if status == "healthy":
        return {
            "level": "none",
            "detail": "Watchdog healthy",
            "last_check": last_check,
        }
    if status == "degraded":
        return {
            "level": "moderate",
            "detail": f"Degraded — {failures} consecutive failures",
            "last_check": last_check,
        }
    if status == "unreachable":
        return {
            "level": "significant",
            "detail": f"Backend unreachable — {failures} failures",
            "last_check": last_check,
        }
    return {"level": "unknown", "detail": f"Unknown status: {status}", "last_check": last_check}


def compute_status_strip() -> dict:
    """Assemble all four status indicators in one dict for the dashboard."""
    active_model = ModelVersion.objects.filter(is_active=True).first()
    return {
        "drift": drift_status(active_model),
        "fairness": fairness_status(active_model),
        "pending_review": pending_review_status(),
        "watchdog": watchdog_status(),
    }
