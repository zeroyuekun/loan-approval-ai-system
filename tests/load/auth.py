"""Login helper for load-test virtual users.

Reads credentials from env vars so no secrets end up in the repo.
"""
import os

LOGIN_PATH = "/api/v1/auth/login/"


def get_credentials() -> tuple[str, str]:
    user = os.environ.get("LOAD_TEST_USER")
    password = os.environ.get("LOAD_TEST_PASSWORD")
    if not user or not password:
        raise RuntimeError(
            "Set LOAD_TEST_USER and LOAD_TEST_PASSWORD env vars. "
            "Seed a test user via: docker compose exec backend python manage.py "
            "createsuperuser (or a dedicated management command)."
        )
    return user, password


def login(client) -> str:
    """POST login. Returns bearer token if body carries one, else empty string.

    This app uses cookie-based JWT (HttpOnly cookies set on login). The Locust
    HttpUser client persists cookies automatically, so downstream requests are
    authenticated without a Bearer header.
    """
    user, password = get_credentials()
    resp = client.post(
        LOGIN_PATH,
        json={"username": user, "password": password},
        name="auth:login",
    )
    if resp.status_code != 200:
        raise RuntimeError(f"login failed: {resp.status_code} {resp.text[:200]}")
    body = resp.json()
    return body.get("access") or body.get("token") or ""
