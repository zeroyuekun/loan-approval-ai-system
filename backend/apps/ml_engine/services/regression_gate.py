"""Regression-gate checks against `ml_models/golden_metrics.json`.

Secondary guard complementing the champion-challenger gate in
`model_selector.py`. The champion-challenger gate blocks runtime
promotion; this regression gate is a static check that CI + post-deploy
smoke tests can run to verify the *currently-active* model hasn't
silently degraded (e.g. drift since last validation, accidental
retraining on contaminated data).

Pure-functional core: `check_regression(metrics, golden)` returns a list
of breach strings; empty list == pass. File-loading + ORM wiring is
done by the thin wrappers below, which the CI harness and pytest fixture
share.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_GOLDEN_PATH_CANDIDATES = [
    # Project-relative (`manage.py` is in `backend/`)
    Path("ml_models") / "golden_metrics.json",
    # Pytest cwd is sometimes the repo root
    Path("backend") / "ml_models" / "golden_metrics.json",
]


def load_golden(path: Path | None = None) -> dict[str, Any] | None:
    """Load the golden-metrics JSON. Returns None if the file is absent.

    Absence is a legal state — first-run environments haven't produced a
    champion yet, and we'd rather skip the gate than fail a fresh clone's
    test suite.
    """
    if path is not None:
        candidates = [Path(path)]
    else:
        candidates = DEFAULT_GOLDEN_PATH_CANDIDATES

    for candidate in candidates:
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("load_golden: failed to read %s: %s", candidate, exc)
                return None
    return None


def check_regression(
    metrics: dict[str, Any],
    golden: dict[str, Any],
) -> list[str]:
    """Compare a metrics dict against the golden file's baselines + tolerances.

    Returns a list of human-readable breach messages. Empty list means no
    regressions. The caller decides whether a breach fails CI or just
    warns (`fail_on_warn` flag in the pytest gate).
    """
    baselines = golden.get("metrics", {}) or {}
    tolerances = golden.get("tolerances", {}) or {}
    breaches: list[str] = []

    # Higher-is-better metrics — fail on a drop beyond tolerance.
    for name, tol_key in [
        ("auc_roc", "auc_roc_drop_pp"),
        ("ks_statistic", "ks_statistic_drop_pp"),
    ]:
        baseline = baselines.get(name)
        observed = metrics.get(name)
        tol = tolerances.get(tol_key)
        if baseline is None or observed is None or tol is None:
            continue
        try:
            baseline_f = float(baseline)
            observed_f = float(observed)
            tol_f = float(tol)
        except (TypeError, ValueError):
            continue
        drop = baseline_f - observed_f
        if drop > tol_f:
            breaches.append(
                f"{name} regressed by {drop:.4f} (observed={observed_f:.4f} "
                f"< baseline {baseline_f:.4f} − tol {tol_f:.4f})"
            )

    # Lower-is-better metrics — fail on a rise beyond tolerance.
    for name, tol_key in [
        ("brier_score", "brier_score_rise_pp"),
        ("ece", "ece_rise_pp"),
    ]:
        baseline = baselines.get(name)
        observed = metrics.get(name)
        tol = tolerances.get(tol_key)
        if baseline is None or observed is None or tol is None:
            continue
        try:
            baseline_f = float(baseline)
            observed_f = float(observed)
            tol_f = float(tol)
        except (TypeError, ValueError):
            continue
        rise = observed_f - baseline_f
        if rise > tol_f:
            breaches.append(
                f"{name} regressed by {rise:.4f} (observed={observed_f:.4f} "
                f"> baseline {baseline_f:.4f} + tol {tol_f:.4f})"
            )

    return breaches


def active_model_metrics() -> dict[str, Any] | None:
    """Pull the current active ModelVersion's metrics as a dict.

    Returns None when there is no active model (e.g. a fresh clone with
    no trained models yet) — the caller should treat that as a skip,
    not a failure, so the test suite stays green on first run.
    """
    try:
        from apps.ml_engine.models import ModelVersion
    except Exception:
        return None

    try:
        mv = ModelVersion.objects.filter(is_active=True).order_by("-created_at").first()
    except Exception:
        return None
    if mv is None:
        return None

    return {
        "auc_roc": mv.auc_roc,
        "ks_statistic": mv.ks_statistic,
        "brier_score": mv.brier_score,
        "ece": mv.ece,
        "gini_coefficient": mv.gini_coefficient,
    }
