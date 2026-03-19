"""Seed customer profiles with bank-known data only (balances, banking relationship).

Customer-entered fields (personal, identity, employment, income, assets,
liabilities, living situation) are left blank so customers fill them in."""
import random
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.accounts.models import CustomUser, CustomerProfile


def _rand_dec(lo, hi, decimals=2):
    return Decimal(str(round(random.uniform(lo, hi), decimals)))


class Command(BaseCommand):
    help = 'Create CustomerProfile with bank-known data only (banking relationship + balances)'

    def handle(self, *args, **options):
        customers = CustomUser.objects.filter(role='customer')
        created = 0
        updated = 0

        for user in customers:
            profile, is_new = CustomerProfile.objects.get_or_create(user=user)
            tag = 'Created' if is_new else 'Updated'

            # --- Banking Relationship (bank-known) ---
            tenure = random.randint(0, 25)
            profile.account_tenure_years = tenure
            profile.num_products = random.randint(1, 6)
            profile.has_credit_card = random.random() > 0.3
            profile.has_mortgage = random.random() > 0.6
            profile.has_auto_loan = random.random() > 0.7
            profile.on_time_payment_pct = round(random.uniform(0.75, 1.0), 4)
            profile.previous_loans_repaid = random.randint(0, 5)

            # Loyalty tier based on tenure & products
            if tenure >= 10 and profile.num_products >= 4:
                profile.loyalty_tier = random.choices(['platinum', 'gold'], weights=[60, 40])[0]
            elif tenure >= 5 and profile.num_products >= 2:
                profile.loyalty_tier = random.choices(['gold', 'silver'], weights=[50, 50])[0]
            elif tenure >= 2:
                profile.loyalty_tier = random.choices(['silver', 'standard'], weights=[40, 60])[0]
            else:
                profile.loyalty_tier = 'standard'

            # Balances (bank-known)
            income_bracket = random.choice(['low', 'mid', 'high'])
            if income_bracket == 'high':
                profile.savings_balance = _rand_dec(20000, 350000)
                profile.checking_balance = _rand_dec(5000, 80000)
            elif income_bracket == 'mid':
                profile.savings_balance = _rand_dec(5000, 80000)
                profile.checking_balance = _rand_dec(1000, 25000)
            else:
                profile.savings_balance = _rand_dec(500, 15000)
                profile.checking_balance = _rand_dec(200, 5000)

            profile.save()
            if is_new:
                created += 1
            else:
                updated += 1
            self.stdout.write(f'  {tag} profile for {user.username} (ID={user.id}) — {profile.loyalty_tier} tier, {tenure}yr tenure')

        self.stdout.write(self.style.SUCCESS(f'\nDone: {created} created, {updated} updated'))
