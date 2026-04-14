"""Locust user classes for the two dominant traffic patterns."""
import time

from locust import HttpUser, between, task

from tests.load.auth import login
from tests.load.payloads import loan_application_payload

TERMINAL_STATES = {"SUCCESS", "FAILURE", "approved", "denied", "failed"}


class _AuthedUser(HttpUser):
    abstract = True

    def on_start(self):
        token = login(self.client)
        if token:
            self.client.headers["Authorization"] = f"Bearer {token}"
        # Else cookie-based auth; HttpUser persists cookies automatically.


class QuickScoreUser(_AuthedUser):
    """70% of load. Creates a loan then hits the synchronous predict endpoint."""

    wait_time = between(1, 3)
    weight = 7

    @task
    def quick_score(self):
        create = self.client.post(
            "/api/v1/loans/",
            json=loan_application_payload(),
            name="loans:create",
        )
        if create.status_code not in (200, 201):
            return
        loan_id = create.json().get("id")
        if not loan_id:
            return
        self.client.post(
            f"/api/v1/ml/predict/{loan_id}/",
            name="ml:predict",
        )


class FullApplicationUser(_AuthedUser):
    """30% of load. Submits application, orchestrates, polls to terminal."""

    wait_time = between(5, 10)
    weight = 3

    @task
    def full_application(self):
        create = self.client.post(
            "/api/v1/loans/",
            json=loan_application_payload(),
            name="loans:create",
        )
        if create.status_code not in (200, 201):
            return
        loan_id = create.json().get("id")
        if not loan_id:
            return

        orchestrate = self.client.post(
            f"/api/v1/agents/orchestrate/{loan_id}/",
            name="agents:orchestrate",
        )
        if orchestrate.status_code not in (200, 202):
            return
        task_id = orchestrate.json().get("task_id") or orchestrate.json().get("id")
        if not task_id:
            return

        deadline = time.time() + 120  # hard cap per iteration
        while time.time() < deadline:
            status_resp = self.client.get(
                f"/api/v1/tasks/{task_id}/status/",
                name="tasks:status",
            )
            if status_resp.status_code != 200:
                return
            state = status_resp.json().get("status") or status_resp.json().get("state")
            if state in TERMINAL_STATES:
                return
            time.sleep(2)
