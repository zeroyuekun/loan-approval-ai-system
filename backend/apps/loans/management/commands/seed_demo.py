"""Seed the demo environment: admin user, synthetic applicants, Neville Zeng golden fixture.

Idempotent — re-running only creates rows that do not already exist.
Used by `make demo` and by the Vercel/self-hosted deployment guide.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand

from apps.accounts.models import CustomUser
from apps.loans.models import LoanApplication
from apps.ml_engine.services.data_generator import DataGenerator


# Fields that DataGenerator emits matching LoanApplication columns. Kept
# narrow on purpose — additional features exist on both sides but are
# optional and default-valued on the model.
_DIRECT_COPY_FIELDS = (
    "annual_income",
    "credit_score",
    "loan_amount",
    "loan_term_months",
    "debt_to_income",
    "employment_length",
    "purpose",
    "home_ownership",
    "monthly_expenses",
    "existing_credit_card_limit",
    "number_of_dependants",
    "employment_type",
    "applicant_type",
    "state",
)

_DECIMAL_FIELDS = {
    "annual_income",
    "loan_amount",
    "debt_to_income",
    "monthly_expenses",
    "existing_credit_card_limit",
}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if _is_missing(value):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 — any parse issue → fall back to the default
        return Decimal(default)


class Command(BaseCommand):
    help = (
        "Seed the demo: admin user, N synthetic applications, and the "
        "Neville Zeng golden fixture. Safe to re-run (idempotent)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--num-records", type=int, default=100)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args: Any, **options: Any) -> None:
        self._seed_admin()
        created = self._seed_synthetic(
            num_records=options["num_records"],
            random_seed=options["seed"],
        )
        self.stdout.write(self.style.SUCCESS(f"Created {created} synthetic applications"))
        self._seed_neville_zeng()

    # -- admin ------------------------------------------------------------
    def _seed_admin(self) -> None:
        admin, created = CustomUser.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@demo.local",
                "role": CustomUser.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "first_name": "Demo",
                "last_name": "Admin",
            },
        )
        if created:
            admin.set_password("demo-admin-password")
            admin.save()
            self.stdout.write(self.style.SUCCESS("Created admin user (username=admin)"))
        else:
            self.stdout.write("Admin user already exists — skipping")

    # -- synthetic applicants --------------------------------------------
    def _seed_synthetic(self, *, num_records: int, random_seed: int) -> int:
        df = DataGenerator().generate(num_records=num_records, random_seed=random_seed)
        created = 0
        for idx, row in enumerate(df.itertuples(index=False)):
            username = f"synthetic_{idx:04d}"
            user, _ = CustomUser.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@demo.local",
                    "role": CustomUser.Role.CUSTOMER,
                    "first_name": "Synthetic",
                    "last_name": f"Applicant{idx:04d}",
                },
            )
            defaults = self._row_to_defaults(row)
            _, app_created = LoanApplication.objects.get_or_create(
                applicant=user,
                defaults=defaults,
            )
            if app_created:
                created += 1
        return created

    def _row_to_defaults(self, row: Any) -> dict[str, Any]:
        defaults: dict[str, Any] = {}
        for field in _DIRECT_COPY_FIELDS:
            value = getattr(row, field, None)
            if _is_missing(value):
                continue
            if field in _DECIMAL_FIELDS:
                defaults[field] = _to_decimal(value)
            elif field in {"credit_score", "loan_term_months", "employment_length", "number_of_dependants"}:
                defaults[field] = int(value)
            else:
                defaults[field] = value
        defaults["has_cosigner"] = bool(getattr(row, "has_cosigner", False))
        defaults["has_hecs"] = bool(getattr(row, "has_hecs", False))
        defaults["has_bankruptcy"] = bool(getattr(row, "has_bankruptcy", False))
        return defaults

    # -- Neville Zeng golden fixture -------------------------------------
    def _seed_neville_zeng(self) -> None:
        nz, _ = CustomUser.objects.get_or_create(
            username="neville_zeng",
            defaults={
                "email": "neville.zeng@demo.local",
                "role": CustomUser.Role.CUSTOMER,
                "first_name": "Neville",
                "last_name": "Zeng",
            },
        )
        _, created = LoanApplication.objects.get_or_create(
            applicant=nz,
            defaults={
                "annual_income": Decimal("120000"),
                "credit_score": 790,
                "loan_amount": Decimal("480000"),
                "loan_term_months": 360,
                "debt_to_income": Decimal("4.00"),
                "employment_length": 6,
                "purpose": LoanApplication.Purpose.HOME,
                "home_ownership": LoanApplication.HomeOwnership.RENT,
                "has_cosigner": False,
                "property_value": Decimal("600000"),
                "deposit_amount": Decimal("120000"),
                "monthly_expenses": Decimal("3200"),
                "existing_credit_card_limit": Decimal("15000"),
                "number_of_dependants": 0,
                "employment_type": LoanApplication.EmploymentType.PAYG_PERMANENT,
                "applicant_type": LoanApplication.ApplicantType.SINGLE,
                "has_hecs": False,
                "has_bankruptcy": False,
                "state": LoanApplication.AustralianState.NSW,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created Neville Zeng golden applicant"))
        else:
            self.stdout.write("Neville Zeng golden applicant already exists — skipping")
