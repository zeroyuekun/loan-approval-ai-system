"""Seed all customer accounts with realistic Australian banking profile data."""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.accounts.models import CustomUser, CustomerProfile


FIRST_NAMES_M = ['James', 'Liam', 'Noah', 'Oliver', 'William', 'Lucas', 'Benjamin', 'Henry', 'Alexander', 'Daniel', 'Matthew', 'Samuel', 'Jack', 'Thomas', 'Ethan']
FIRST_NAMES_F = ['Charlotte', 'Amelia', 'Olivia', 'Isla', 'Mia', 'Ava', 'Grace', 'Willow', 'Harper', 'Chloe', 'Ella', 'Sophie', 'Emily', 'Lily', 'Zoe']
SUBURBS = [
    ('Parramatta', 'NSW', '2150'), ('Bondi', 'NSW', '2026'), ('Chatswood', 'NSW', '2067'),
    ('South Yarra', 'VIC', '3141'), ('Richmond', 'VIC', '3121'), ('Carlton', 'VIC', '3053'),
    ('Fortitude Valley', 'QLD', '4006'), ('Southport', 'QLD', '4215'), ('Toowong', 'QLD', '4066'),
    ('Subiaco', 'WA', '6008'), ('Fremantle', 'WA', '6160'), ('Joondalup', 'WA', '6027'),
    ('Glenelg', 'SA', '5045'), ('Norwood', 'SA', '5067'),
    ('Sandy Bay', 'TAS', '7005'), ('Braddon', 'ACT', '2612'),
]
STREETS = [
    '12 George St', '45 Smith Ave', '7 King St', '23 Park Rd', '88 High St',
    '5 Ocean Dr', '101 Railway Pde', '33 Church St', '19 Victoria Ave', '62 William St',
    '14 Albert Rd', '28 Elizabeth St', '9 Bridge Rd', '55 Main St', '41 Market St',
    '16 Collins St', '73 Murray St', '38 Pitt St', '27 Queen St', '8 Bourke St',
]
EMPLOYERS = [
    'Commonwealth Bank', 'BHP Group', 'Telstra', 'Woolworths Group', 'Wesfarmers',
    'National Australia Bank', 'Westpac', 'ANZ', 'Macquarie Group', 'Rio Tinto',
    'CSL Limited', 'Transurban', 'Woodside Energy', 'Fortescue Metals', 'Brambles',
    'Cochlear', 'ResMed', 'Atlassian', 'Canva', 'Xero',
    'NSW Health', 'VIC Department of Education', 'QLD Police Service',
    'Australian Defence Force', 'PwC Australia', 'Deloitte Australia',
    'KPMG Australia', 'Ernst & Young', 'Santos Limited', 'Qantas Airways',
]
OCCUPATIONS = [
    'Software Engineer', 'Registered Nurse', 'Accountant', 'Teacher', 'Electrician',
    'Project Manager', 'Civil Engineer', 'Marketing Manager', 'Financial Analyst', 'Pharmacist',
    'Solicitor', 'Architect', 'Data Analyst', 'Operations Manager', 'HR Manager',
    'Physiotherapist', 'Dentist', 'Mechanic', 'Chef', 'Police Officer',
    'Paramedic', 'Social Worker', 'Quantity Surveyor', 'Mining Engineer', 'Geologist',
]
INDUSTRIES = [
    'financial_insurance', 'mining', 'information_media', 'retail_trade', 'construction',
    'healthcare_social', 'education_training', 'professional_scientific', 'public_admin',
    'transport_postal', 'manufacturing', 'accommodation_food', 'property_services',
    'administrative', 'utilities', 'wholesale_trade', 'agriculture', 'arts_recreation',
]


def _rand_dec(lo, hi, decimals=2):
    return Decimal(str(round(random.uniform(lo, hi), decimals)))


class Command(BaseCommand):
    help = 'Create realistic CustomerProfile for every customer user'

    def handle(self, *args, **options):
        customers = CustomUser.objects.filter(role='customer')
        created = 0
        updated = 0

        for user in customers:
            profile, is_new = CustomerProfile.objects.get_or_create(user=user)
            tag = 'Created' if is_new else 'Updated'

            # --- Personal ---
            age = random.randint(22, 65)
            profile.date_of_birth = date.today() - timedelta(days=age * 365 + random.randint(0, 364))
            profile.phone = f'04{random.randint(10, 99)} {random.randint(100, 999)} {random.randint(100, 999)}'
            suburb_data = random.choice(SUBURBS)
            profile.address_line_1 = random.choice(STREETS)
            profile.address_line_2 = ''
            profile.suburb = suburb_data[0]
            profile.state = suburb_data[1]
            profile.postcode = suburb_data[2]
            profile.marital_status = random.choice(['single', 'married', 'de_facto', 'divorced', 'widowed'])

            # --- Identity ---
            profile.residency_status = random.choices(
                ['citizen', 'permanent_resident', 'temporary_visa', 'nz_citizen'],
                weights=[70, 15, 10, 5],
            )[0]
            profile.primary_id_type = random.choice(['drivers_licence', 'passport'])
            profile.primary_id_number = f'{random.choice(["NSW","VIC","QLD","WA","SA"])}{random.randint(1000000, 9999999)}'
            profile.secondary_id_type = random.choice(['medicare', 'passport', 'immicard'])
            profile.secondary_id_number = f'{random.randint(2000, 9999)} {random.randint(10000, 99999)} {random.randint(1, 9)}'
            profile.tax_file_number_provided = random.random() > 0.1
            profile.is_politically_exposed = random.random() < 0.02

            # --- Banking Relationship ---
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

            # Balances scale with age/income bracket
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

            # --- Employment ---
            profile.employment_status = random.choices(
                ['payg_permanent', 'payg_casual', 'self_employed', 'contract'],
                weights=[55, 15, 20, 10],
            )[0]
            profile.employer_name = random.choice(EMPLOYERS)
            profile.occupation = random.choice(OCCUPATIONS)
            profile.industry = random.choice(INDUSTRIES)
            years_role = round(random.uniform(0.5, 20), 1)
            profile.years_in_current_role = Decimal(str(years_role))
            if years_role < 2:
                profile.previous_employer = random.choice(EMPLOYERS)
            else:
                profile.previous_employer = ''

            # --- Income ---
            if income_bracket == 'high':
                profile.gross_annual_income = _rand_dec(120000, 400000)
            elif income_bracket == 'mid':
                profile.gross_annual_income = _rand_dec(65000, 120000)
            else:
                profile.gross_annual_income = _rand_dec(42000, 65000)

            if random.random() > 0.6:
                profile.other_income = _rand_dec(2000, 30000)
                profile.other_income_source = random.choice([
                    'Rental income', 'Investment dividends', 'Share trading',
                    'Part-time work', 'Freelance consulting', 'Government benefits',
                ])
            else:
                profile.other_income = Decimal('0')
                profile.other_income_source = ''

            if profile.marital_status in ('married', 'de_facto'):
                profile.partner_annual_income = _rand_dec(35000, 200000)
            else:
                profile.partner_annual_income = None

            # --- Assets ---
            if profile.has_mortgage or random.random() > 0.5:
                profile.estimated_property_value = _rand_dec(350000, 2500000)
            else:
                profile.estimated_property_value = Decimal('0')

            profile.vehicle_value = _rand_dec(0, 80000) if random.random() > 0.3 else Decimal('0')
            profile.savings_other_institutions = _rand_dec(0, 50000) if random.random() > 0.4 else Decimal('0')
            profile.investment_value = _rand_dec(0, 200000) if random.random() > 0.5 else Decimal('0')

            if age > 30:
                profile.superannuation_balance = _rand_dec(20000, 800000)
            else:
                profile.superannuation_balance = _rand_dec(5000, 60000)

            # --- Liabilities ---
            profile.other_loan_repayments_monthly = _rand_dec(0, 3000) if random.random() > 0.5 else Decimal('0')
            profile.other_credit_card_limits = _rand_dec(0, 25000) if profile.has_credit_card else Decimal('0')
            profile.rent_or_board_monthly = _rand_dec(800, 3500) if random.random() > 0.4 else Decimal('0')

            # --- Living ---
            profile.housing_situation = random.choice(['own_outright', 'mortgage', 'renting', 'boarding', 'living_with_parents'])
            addr_years = round(random.uniform(0.5, 15), 1)
            profile.time_at_current_address_years = Decimal(str(addr_years))
            profile.number_of_dependants = random.choices(
                [0, 1, 2, 3, 4, 5],
                weights=[35, 20, 25, 12, 5, 3],
            )[0]

            if addr_years < 3:
                prev = random.choice(SUBURBS)
                profile.previous_suburb = prev[0]
                profile.previous_state = prev[1]
                profile.previous_postcode = prev[2]
            else:
                profile.previous_suburb = ''
                profile.previous_state = ''
                profile.previous_postcode = ''

            profile.preferred_contact_method = random.choice(['email', 'phone', 'sms'])

            profile.save()
            if is_new:
                created += 1
            else:
                updated += 1
            self.stdout.write(f'  {tag} profile for {user.username} (ID={user.id}) — {profile.loyalty_tier} tier, {tenure}yr tenure')

        self.stdout.write(self.style.SUCCESS(f'\nDone: {created} created, {updated} updated'))
