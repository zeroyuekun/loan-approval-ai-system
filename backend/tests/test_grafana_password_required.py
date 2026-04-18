"""Guard: Grafana must not ship a default admin password.

Issue #57 — we previously had `GRAFANA_ADMIN_PASSWORD:-changeme` in
`docker-compose.yml` which silently gave every fresh clone the literal
string `changeme` as the monitoring admin password. Grafana is now
isolated in `docker-compose.monitoring.yml` with the `:?` required-env
form so compose refuses to start the monitoring profile without an
explicit secret.

In CI the working directory is the repo root. When running inside the
backend container (`/app`), the compose files are not mounted — we
skip the test there since the invariant is already enforced by CI.
"""

from pathlib import Path

import pytest


def test_monitoring_compose_has_required_grafana_password():
    repo_root = Path(__file__).resolve().parents[2]
    monitoring_compose = repo_root / "docker-compose.monitoring.yml"

    if not monitoring_compose.exists():
        pytest.skip(f"{monitoring_compose} not reachable — guard enforced by CI runner")

    compose = monitoring_compose.read_text(encoding="utf-8")

    assert "GRAFANA_ADMIN_PASSWORD" in compose, "docker-compose.monitoring.yml should reference GRAFANA_ADMIN_PASSWORD"
    assert ":-changeme" not in compose, (
        "docker-compose.monitoring.yml still ships `:-changeme` fallback — "
        "replace with `${GRAFANA_ADMIN_PASSWORD:?...}` so compose fails fast "
        "when the env var is missing."
    )
    assert "GRAFANA_ADMIN_PASSWORD:?" in compose, (
        "docker-compose.monitoring.yml should use `${GRAFANA_ADMIN_PASSWORD:?...}` "
        "(required-env form) so compose fails fast when the secret is unset."
    )


def test_main_compose_does_not_ship_grafana_changeme_default():
    repo_root = Path(__file__).resolve().parents[2]
    main_compose = repo_root / "docker-compose.yml"

    if not main_compose.exists():
        pytest.skip(f"{main_compose} not reachable — guard enforced by CI runner")

    compose = main_compose.read_text(encoding="utf-8")

    assert "GRAFANA_ADMIN_PASSWORD:-changeme" not in compose, (
        "docker-compose.yml must not re-introduce the :-changeme default. "
        "Grafana belongs in docker-compose.monitoring.yml with the `:?` form."
    )
