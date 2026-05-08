"""Seed AU-realistic synthetic predictions against a ModelVersion.

Generates a synthetic loan-application stream via DataGenerator (already
calibrated against ABS/APRA/RBA/HILDA), runs each through the model, and
overrides created_at with a weekday-business + evening-biased timestamp
distribution that mimics an online consumer-lending application stream.

Optionally triggers compute_weekly_drift_report.apply() at the end so a
real DriftReport row is produced (drift task otherwise short-circuits if
no recent predictions exist).
"""

import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.ml_engine.models import ModelVersion, PredictionLog


# Day-of-week weights — Tue/Wed peak with weekend tail.
DOW_WEIGHTS = [13, 22, 22, 18, 12, 8, 5]  # Mon..Sun (sums to 100)

# Hour-of-day weights — bimodal: 8-10am small peak, 6-9pm large peak.
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 1, 2, 3, 5, 6, 5, 4, 4, 4, 4, 4, 5, 6, 8, 9, 9, 7, 4, 2]


class Command(BaseCommand):
    help = (
        "Seed an AU-realistic synthetic prediction stream for a ModelVersion "
        "and (optionally) trigger the drift task."
    )

    def add_arguments(self, parser):
        parser.add_argument("--model-id", type=str, required=True, help="ModelVersion UUID")
        parser.add_argument(
            "--count", type=int, default=200,
            help="Number of predictions (1..10000, default 200)",
        )
        parser.add_argument(
            "--spread-days", type=int, default=7,
            help="Window in days for created_at (1..90, default 7)",
        )
        parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
        parser.add_argument("--trigger-drift", dest="trigger_drift", action="store_true", default=True)
        parser.add_argument("--no-trigger-drift", dest="trigger_drift", action="store_false")

    def handle(self, *args, **options):
        from apps.ml_engine.services.data_generator import DataGenerator
        from apps.ml_engine.services.predictor import ModelPredictor

        count = options["count"]
        spread_days = options["spread_days"]
        seed = options["seed"]

        if not (1 <= count <= 10000):
            raise CommandError(f"--count must be in [1, 10000], got {count}")
        if not (1 <= spread_days <= 90):
            raise CommandError(f"--spread-days must be in [1, 90], got {spread_days}")

        try:
            mv = ModelVersion.objects.get(id=options["model_id"])
        except ModelVersion.DoesNotExist:
            raise CommandError(f"ModelVersion {options['model_id']} not found")

        rng = random.Random(seed) if seed is not None else random.Random()

        df = DataGenerator().generate(num_records=count, random_seed=seed or 42, label_noise_rate=0.05)
        if len(df) < count:
            raise CommandError(f"DataGenerator returned {len(df)} rows, expected {count}")
        df = df.iloc[:count].reset_index(drop=True)

        predictor = ModelPredictor(model_version=mv)

        # Create a shared seed user + application for all synthetic PredictionLog rows.
        # This avoids N user+application inserts while satisfying the non-null FK
        # constraint. The application is tagged with the model version so it can
        # be identified and cleaned up if needed.
        seed_app = self._get_or_create_seed_application(mv)

        created_rows = []
        with transaction.atomic():
            for i in range(count):
                row = df.iloc[i].to_dict()
                try:
                    result = predictor.predict(row)
                except Exception as exc:
                    raise CommandError(f"predict() failed on row {i}: {exc}")

                decision = result.get("decision") or result.get("prediction", "approve")
                probability = float(result.get("probability", 0.0))

                pl = PredictionLog.objects.create(
                    model_version=mv,
                    application=seed_app,
                    prediction=str(decision),
                    probability=probability,
                )
                created_rows.append(pl)

        # Override created_at to weekday + evening-biased timestamps.
        # bulk_update issues SQL UPDATE which bypasses auto_now_add (applies
        # only to INSERT), so the sampled timestamps replace the originals.
        #
        # window_start is anchored at midnight of (today - (spread_days - 1))
        # so that adding `day_offset` days lands on a predictable calendar date
        # regardless of the current time-of-day.  Without this, a late-afternoon
        # `now` would shift most timestamps into the *following* calendar day
        # once the evening hour bias is added, making the measured DOW
        # distribution diverge from the intended DOW_WEIGHTS shape.
        # Anchoring to today's midnight - (spread_days - 1) keeps the earliest
        # possible timestamp well inside the `now - spread_days - 1h` lower
        # bound checked by the window test.
        now = timezone.now()
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today_midnight - timedelta(days=spread_days - 1)
        dow_weights_for_window = self._dow_weights_for_window(spread_days, now)
        for pl in created_rows:
            day_offset = rng.choices(
                range(spread_days),
                weights=dow_weights_for_window[:spread_days],
                k=1,
            )[0]
            hour = rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]
            minute = rng.randrange(60)
            second = rng.randrange(60)
            sampled = window_start + timedelta(
                days=day_offset, hours=hour, minutes=minute, seconds=second,
            )
            # Clamp to window bounds.
            if sampled > now:
                sampled = now - timedelta(seconds=rng.randrange(60))
            if sampled < window_start:
                sampled = window_start + timedelta(seconds=rng.randrange(60))
            pl.created_at = sampled

        PredictionLog.objects.bulk_update(created_rows, ["created_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {count} predictions for {mv.algorithm} v{mv.version}"
            )
        )

        if options["trigger_drift"]:
            from apps.ml_engine.tasks import compute_weekly_drift_report
            self.stdout.write("Triggering compute_weekly_drift_report.apply() ...")
            result = compute_weekly_drift_report.apply()
            self.stdout.write(f"Drift task result: {result.result}")

    def _get_or_create_seed_application(self, mv):
        """Return (creating if needed) a synthetic seed LoanApplication.

        A single synthetic application is shared by all PredictionLog rows
        produced by this command run. We reuse it across runs keyed by
        a deterministic seed username so the table doesn't grow unboundedly.
        """
        from decimal import Decimal

        from apps.accounts.models import CustomUser
        from apps.loans.models import LoanApplication

        seed_username = f"seed_predictions_mv_{mv.id}"
        user, _ = CustomUser.objects.get_or_create(
            username=seed_username,
            defaults={
                "email": f"{seed_username}@seed.internal",
                "role": "customer",
                "is_active": False,
            },
        )

        app = LoanApplication.objects.filter(applicant=user).first()
        if app is None:
            app = LoanApplication.objects.create(
                applicant=user,
                annual_income=Decimal("75000.00"),
                credit_score=700,
                loan_amount=Decimal("25000.00"),
                loan_term_months=36,
                debt_to_income=Decimal("1.50"),
                employment_length=5,
                purpose="personal",
                home_ownership="rent",
                has_cosigner=False,
                monthly_expenses=Decimal("2200.00"),
                existing_credit_card_limit=Decimal("8000.00"),
                number_of_dependants=0,
                employment_type="payg_permanent",
                applicant_type="single",
                has_hecs=False,
                has_bankruptcy=False,
                state="NSW",
                status=LoanApplication.Status.APPROVED,
            )
        return app

    def _dow_weights_for_window(self, spread_days, now):
        """Return weights aligned to weekday positions for a `spread_days`-long window.

        The window used by `handle()` is anchored at midnight of
        `today - (spread_days - 1)`.  Each position `offset` in `[0, spread_days)`
        maps to calendar day `window_start + offset`.  Because `window_start` is
        at midnight, adding any hour in [0, 23] never crosses into the next
        calendar day, so the DOW weight at position `offset` exactly predicts
        the weekday of the sampled timestamp — the highest-weight offsets land
        reliably on Tue/Wed regardless of what time the command is run.
        """
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today_midnight - timedelta(days=spread_days - 1)
        weights = []
        for offset in range(spread_days):
            sampled_day = window_start + timedelta(days=offset)
            weights.append(DOW_WEIGHTS[sampled_day.weekday()])
        return weights
