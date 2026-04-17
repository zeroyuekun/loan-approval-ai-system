"""Load test scenarios for AussieLoanAI.

Simulates realistic traffic patterns:
- 20% monitoring/health checks
- 50% read-heavy browsing (login, list, view)
- 30% write-heavy applicant flow (register, apply, predict)
"""
import json
import random
import string
from locust import HttpUser, task, between, tag


class HealthCheckUser(HttpUser):
    """Simulates monitoring systems hitting health endpoints."""
    weight = 2
    wait_time = between(1, 3)

    @tag('health')
    @task(3)
    def health(self):
        self.client.get('/api/v1/health/', name='/health')

    @tag('health')
    @task(1)
    def deep_health(self):
        self.client.get('/api/v1/health/deep/', name='/health/deep')


class BrowsingUser(HttpUser):
    """Simulates logged-in users browsing the dashboard."""
    weight = 5
    wait_time = between(2, 5)
    token = None

    def on_start(self):
        """Login on start."""
        resp = self.client.post('/api/v1/auth/login/', json={
            'username': 'demo_customer',
            'password': 'DemoPass123!',
        })
        if resp.status_code == 200:
            # Cookie-based auth — cookies are stored automatically
            pass

    @tag('browse')
    @task(3)
    def list_loans(self):
        self.client.get('/api/v1/loans/', name='/loans [list]')

    @tag('browse')
    @task(2)
    def view_metrics(self):
        self.client.get('/api/v1/ml/metrics/', name='/ml/metrics')

    @tag('browse')
    @task(1)
    def list_emails(self):
        self.client.get('/api/v1/emails/', name='/emails [list]')

    @tag('browse')
    @task(1)
    def view_drift(self):
        self.client.get('/api/v1/ml/drift/', name='/ml/drift')


class ApplicantUser(HttpUser):
    """Simulates new customers applying for loans."""
    weight = 3
    wait_time = between(3, 8)
    username = None

    def on_start(self):
        """Register a unique user."""
        self.username = f'loadtest_{"".join(random.choices(string.ascii_lowercase, k=8))}'
        self.client.post('/api/v1/auth/register/', json={
            'username': self.username,
            'email': f'{self.username}@loadtest.com',
            'password': 'LoadTest123!',
            'password2': 'LoadTest123!',
            'first_name': 'Load',
            'last_name': 'Tester',
        })
        self.client.post('/api/v1/auth/login/', json={
            'username': self.username,
            'password': 'LoadTest123!',
        })

    @tag('apply')
    @task(1)
    def create_application(self):
        """Submit a loan application."""
        self.client.post('/api/v1/loans/', json={
            'annual_income': random.randint(50000, 200000),
            'credit_score': random.randint(650, 1000),
            'loan_amount': random.randint(10000, 500000),
            'loan_term_months': random.choice([36, 60, 120, 240, 360]),
            'debt_to_income': round(random.uniform(1.0, 5.0), 2),
            'employment_length': random.randint(1, 20),
            'purpose': random.choice(['home', 'personal', 'auto', 'business', 'education']),
            'home_ownership': random.choice(['own', 'rent', 'mortgage']),
            'employment_type': random.choice(['payg_permanent', 'payg_casual', 'self_employed', 'contract']),
            'applicant_type': random.choice(['single', 'couple']),
            'has_cosigner': False,
            'monthly_expenses': random.randint(2000, 6000),
            'existing_credit_card_limit': random.randint(0, 20000),
            'number_of_dependants': random.randint(0, 4),
            'state': random.choice(['NSW', 'VIC', 'QLD', 'WA', 'SA']),
        }, name='/loans [create]')

    @tag('apply')
    @task(1)
    def list_my_loans(self):
        self.client.get('/api/v1/loans/', name='/loans [list]')
