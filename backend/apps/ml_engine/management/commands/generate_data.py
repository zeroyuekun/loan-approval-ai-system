import math
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.accounts.models import CustomerProfile, CustomUser
from apps.loans.models import LoanApplication
from apps.ml_engine.services.data_generator import DataGenerator

# Realistic Australian demo customers
DEMO_CUSTOMERS = [
    {'username': 'demo_customer', 'first_name': 'James', 'last_name': 'Mitchell', 'email': 'james.mitchell@example.com'},
    {'username': 'sarah_chen', 'first_name': 'Sarah', 'last_name': 'Chen', 'email': 'sarah.chen@example.com'},
    {'username': 'liam_oconnor', 'first_name': 'Liam', 'last_name': "O'Connor", 'email': 'liam.oconnor@example.com'},
    {'username': 'priya_sharma', 'first_name': 'Priya', 'last_name': 'Sharma', 'email': 'priya.sharma@example.com'},
    {'username': 'olivia_taylor', 'first_name': 'Olivia', 'last_name': 'Taylor', 'email': 'olivia.taylor@example.com'},
    {'username': 'mohammed_ali', 'first_name': 'Mohammed', 'last_name': 'Ali', 'email': 'mohammed.ali@example.com'},
    {'username': 'emma_williams', 'first_name': 'Emma', 'last_name': 'Williams', 'email': 'emma.williams@example.com'},
    {'username': 'david_nguyen', 'first_name': 'David', 'last_name': 'Nguyen', 'email': 'david.nguyen@example.com'},
    {'username': 'jessica_brown', 'first_name': 'Jessica', 'last_name': 'Brown', 'email': 'jessica.brown@example.com'},
    {'username': 'marco_rossi', 'first_name': 'Marco', 'last_name': 'Rossi', 'email': 'marco.rossi@example.com'},
    {'username': 'chloe_martin', 'first_name': 'Chloe', 'last_name': 'Martin', 'email': 'chloe.martin@example.com'},
    {'username': 'raj_patel', 'first_name': 'Raj', 'last_name': 'Patel', 'email': 'raj.patel@example.com'},
    {'username': 'sophie_jones', 'first_name': 'Sophie', 'last_name': 'Jones', 'email': 'sophie.jones@example.com'},
    {'username': 'tom_anderson', 'first_name': 'Tom', 'last_name': 'Anderson', 'email': 'tom.anderson@example.com'},
    {'username': 'mei_lin_wong', 'first_name': 'Mei Lin', 'last_name': 'Wong', 'email': 'meilin.wong@example.com'},
    {'username': 'jack_harris', 'first_name': 'Jack', 'last_name': 'Harris', 'email': 'jack.harris@example.com'},
    {'username': 'amara_okafor', 'first_name': 'Amara', 'last_name': 'Okafor', 'email': 'amara.okafor@example.com'},
    {'username': 'ben_thompson', 'first_name': 'Ben', 'last_name': 'Thompson', 'email': 'ben.thompson@example.com'},
    {'username': 'yuki_tanaka', 'first_name': 'Yuki', 'last_name': 'Tanaka', 'email': 'yuki.tanaka@example.com'},
    {'username': 'grace_kelly', 'first_name': 'Grace', 'last_name': 'Kelly', 'email': 'grace.kelly@example.com'},
    {'username': 'chris_dimitriou', 'first_name': 'Chris', 'last_name': 'Dimitriou', 'email': 'chris.dimitriou@example.com'},
    {'username': 'natalie_white', 'first_name': 'Natalie', 'last_name': 'White', 'email': 'natalie.white@example.com'},
    {'username': 'sam_robinson', 'first_name': 'Sam', 'last_name': 'Robinson', 'email': 'sam.robinson@example.com'},
    {'username': 'fatima_hassan', 'first_name': 'Fatima', 'last_name': 'Hassan', 'email': 'fatima.hassan@example.com'},
    {'username': 'daniel_lee', 'first_name': 'Daniel', 'last_name': 'Lee', 'email': 'daniel.lee@example.com'},
]

# Australian addresses by suburb
AU_ADDRESSES = [
    {'line_1': '42 Oxford Street', 'suburb': 'Surry Hills', 'state': 'NSW', 'postcode': '2010'},
    {'line_1': '15 Brunswick Street', 'suburb': 'Fitzroy', 'state': 'VIC', 'postcode': '3065'},
    {'line_1': '8 James Street', 'suburb': 'Fortitude Valley', 'state': 'QLD', 'postcode': '4006'},
    {'line_1': '23 High Street', 'suburb': 'Fremantle', 'state': 'WA', 'postcode': '6160'},
    {'line_1': '91 Jetty Road', 'suburb': 'Glenelg', 'state': 'SA', 'postcode': '5045'},
    {'line_1': '5 Sandy Bay Road', 'suburb': 'Sandy Bay', 'state': 'TAS', 'postcode': '7005'},
    {'line_1': '17 Lonsdale Street', 'suburb': 'Braddon', 'state': 'ACT', 'postcode': '2612'},
    {'line_1': '33 Mitchell Street', 'suburb': 'Darwin City', 'state': 'NT', 'postcode': '0800'},
    {'line_1': '112 George Street', 'suburb': 'The Rocks', 'state': 'NSW', 'postcode': '2000'},
    {'line_1': '7 Chapel Street', 'suburb': 'South Yarra', 'state': 'VIC', 'postcode': '3141'},
    {'line_1': '29 Boundary Street', 'suburb': 'West End', 'state': 'QLD', 'postcode': '4101'},
    {'line_1': '64 Beaufort Street', 'suburb': 'Perth', 'state': 'WA', 'postcode': '6000'},
    {'line_1': '3 King William Road', 'suburb': 'Unley', 'state': 'SA', 'postcode': '5061'},
    {'line_1': '51 Liverpool Street', 'suburb': 'Hobart', 'state': 'TAS', 'postcode': '7000'},
    {'line_1': '20 Mort Street', 'suburb': 'Canberra City', 'state': 'ACT', 'postcode': '2601'},
    {'line_1': '78 Military Road', 'suburb': 'Neutral Bay', 'state': 'NSW', 'postcode': '2089'},
    {'line_1': '14 Acland Street', 'suburb': 'St Kilda', 'state': 'VIC', 'postcode': '3182'},
    {'line_1': '56 Caxton Street', 'suburb': 'Paddington', 'state': 'QLD', 'postcode': '4064'},
    {'line_1': '9 Stirling Highway', 'suburb': 'Claremont', 'state': 'WA', 'postcode': '6010'},
    {'line_1': '38 Rundle Street', 'suburb': 'Adelaide', 'state': 'SA', 'postcode': '5000'},
    {'line_1': '145 Parramatta Road', 'suburb': 'Annandale', 'state': 'NSW', 'postcode': '2038'},
    {'line_1': '22 Glenferrie Road', 'suburb': 'Hawthorn', 'state': 'VIC', 'postcode': '3122'},
    {'line_1': '11 Logan Road', 'suburb': 'Woolloongabba', 'state': 'QLD', 'postcode': '4102'},
    {'line_1': '67 Hay Street', 'suburb': 'Subiaco', 'state': 'WA', 'postcode': '6008'},
    {'line_1': '4 The Parade', 'suburb': 'Norwood', 'state': 'SA', 'postcode': '5067'},
]

UNIT_PREFIXES = ['Unit', 'Apt', 'Level']


def _random_dob(min_age=22, max_age=65):
    today = date.today()
    age = random.randint(min_age, max_age)
    dob = today.replace(year=today.year - age) - timedelta(days=random.randint(0, 364))
    return dob


def _random_phone():
    return f'04{random.randint(10, 99)} {random.randint(100, 999)} {random.randint(100, 999)}'


def _safe_val(row, col, cast=float, default=None):
    """Convert DataFrame value to Django-safe value, handling NaN."""
    val = row.get(col)
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return cast(val)


def _build_profile_data(index):
    """Generate realistic, correlated profile data for a customer."""
    addr = AU_ADDRESSES[index % len(AU_ADDRESSES)]
    tenure = random.choices(
        [random.randint(0, 2), random.randint(3, 7), random.randint(8, 12), random.randint(13, 20)],
        weights=[15, 40, 30, 15],
    )[0]

    # Correlated: longer tenure → higher tier, more products
    if tenure >= 10:
        tier = random.choices(['gold', 'platinum'], weights=[40, 60])[0]
        num_products = random.randint(3, 6)
    elif tenure >= 5:
        tier = random.choices(['silver', 'gold'], weights=[50, 50])[0]
        num_products = random.randint(2, 5)
    elif tenure >= 2:
        tier = random.choices(['standard', 'silver'], weights=[60, 40])[0]
        num_products = random.randint(1, 3)
    else:
        tier = 'standard'
        num_products = random.randint(1, 2)

    has_mortgage = random.random() < (0.5 if tenure >= 5 else 0.2)
    has_credit_card = random.random() < (0.8 if tenure >= 3 else 0.5)
    has_auto_loan = random.random() < (0.3 if tenure >= 2 else 0.1)

    # Savings correlated with tenure and tier
    savings_base = {'standard': 5000, 'silver': 15000, 'gold': 35000, 'platinum': 60000}
    savings = round(random.uniform(savings_base[tier] * 0.5, savings_base[tier] * 2.5), 2)
    checking = round(random.uniform(1000, 20000), 2)

    on_time_pct = round(random.uniform(
        95.0 if tier in ('gold', 'platinum') else 88.0,
        100.0,
    ), 1)
    prev_repaid = random.randint(
        1 if tenure >= 3 else 0,
        min(tenure // 2 + 1, 6),
    )

    residency = random.choices(
        ['citizen', 'permanent_resident', 'temporary_visa', 'nz_citizen'],
        weights=[70, 18, 7, 5],
    )[0]

    marital = random.choices(
        ['single', 'married', 'de_facto', 'divorced', 'widowed'],
        weights=[30, 35, 20, 12, 3],
    )[0]

    primary_id = random.choice(['drivers_licence', 'passport'])
    secondary_id = 'medicare' if primary_id == 'drivers_licence' else random.choice(['drivers_licence', 'medicare'])

    has_unit = random.random() < 0.35
    address_line_2 = f'{random.choice(UNIT_PREFIXES)} {random.randint(1, 20)}' if has_unit else ''

    return {
        'date_of_birth': _random_dob(),
        'phone': _random_phone(),
        'address_line_1': addr['line_1'],
        'address_line_2': address_line_2,
        'suburb': addr['suburb'],
        'state': addr['state'],
        'postcode': addr['postcode'],
        'marital_status': marital,
        'residency_status': residency,
        'primary_id_type': primary_id,
        'primary_id_number': f'{random.randint(10000000, 99999999)}',
        'secondary_id_type': secondary_id,
        'secondary_id_number': f'{random.randint(2000, 9999)} {random.randint(10000, 99999)} {random.randint(1, 9)}',
        'tax_file_number_provided': random.random() < 0.85,
        'is_politically_exposed': random.random() < 0.02,
        'account_tenure_years': tenure,
        'loyalty_tier': tier,
        'num_products': num_products,
        'savings_balance': savings,
        'checking_balance': checking,
        'has_credit_card': has_credit_card,
        'has_mortgage': has_mortgage,
        'has_auto_loan': has_auto_loan,
        'on_time_payment_pct': on_time_pct,
        'previous_loans_repaid': prev_repaid,
    }


class Command(BaseCommand):
    help = 'Generate synthetic loan application data for model training'

    def add_arguments(self, parser):
        parser.add_argument(
            '--num-records', type=int, default=50000,
            help='Number of records to generate (default: 50000)',
        )
        parser.add_argument(
            '--output', type=str, default='.tmp/synthetic_loans.csv',
            help='Output CSV file path (default: .tmp/synthetic_loans.csv)',
        )
        parser.add_argument(
            '--create-db-records', type=int, default=100,
            help='Number of LoanApplication records to create in DB (default: 100)',
        )
        parser.add_argument(
            '--label-noise-rate', type=float, default=0.05,
            help='Fraction of approved loans flipped to denied as label noise (default: 0.05)',
        )

    def handle(self, *args, **options):
        num_records = options['num_records']
        output_path = options['output']
        db_count = options['create_db_records']
        label_noise_rate = options['label_noise_rate']

        self.stdout.write(f'Generating {num_records} synthetic loan records...')

        generator = DataGenerator()
        df = generator.generate(num_records=num_records, label_noise_rate=label_noise_rate)
        generator.save_to_csv(df, output_path)

        self.stdout.write(self.style.SUCCESS(f'Saved {num_records} records to {output_path}'))

        # Create DB records for a subset
        if db_count > 0:
            self.stdout.write(f'Creating {db_count} LoanApplication records in DB...')

            # Create demo customers with fully populated profiles
            customers = []
            for i, cust_data in enumerate(DEMO_CUSTOMERS):
                user, created = CustomUser.objects.get_or_create(
                    username=cust_data['username'],
                    defaults={
                        'email': cust_data['email'],
                        'role': 'customer',
                        'first_name': cust_data['first_name'],
                        'last_name': cust_data['last_name'],
                    },
                )
                if created:
                    user.set_password('demo1234')
                    user.save()

                # Populate profile with realistic Australian data
                profile_data = _build_profile_data(i)
                CustomerProfile.objects.update_or_create(
                    user=user,
                    defaults=profile_data,
                )
                customers.append(user)

            self.stdout.write(self.style.SUCCESS(
                f'Created/updated {len(customers)} demo customers with full profiles'
            ))

            # Distribute loan applications across customers (round-robin)
            subset = df.sample(n=min(db_count, len(df)), random_state=42)
            created_count = 0
            for idx, (_, row) in enumerate(subset.iterrows()):
                applicant = customers[idx % len(customers)]
                LoanApplication.objects.create(
                    applicant=applicant,
                    annual_income=row['annual_income'],
                    credit_score=int(row['credit_score']),
                    loan_amount=row['loan_amount'],
                    loan_term_months=int(row['loan_term_months']),
                    debt_to_income=round(row['debt_to_income'], 2),
                    employment_length=int(row['employment_length']),
                    purpose=row['purpose'],
                    home_ownership=row['home_ownership'],
                    has_cosigner=bool(row['has_cosigner']),
                    property_value=row['property_value'] if not (isinstance(row['property_value'], float) and math.isnan(row['property_value'])) and row['property_value'] > 0 else None,
                    deposit_amount=row['deposit_amount'] if not (isinstance(row['deposit_amount'], float) and math.isnan(row['deposit_amount'])) and row['deposit_amount'] > 0 else None,
                    monthly_expenses=row['monthly_expenses'] if not (isinstance(row['monthly_expenses'], float) and math.isnan(row['monthly_expenses'])) else None,
                    existing_credit_card_limit=row['existing_credit_card_limit'] if not (isinstance(row['existing_credit_card_limit'], float) and math.isnan(row['existing_credit_card_limit'])) else 0,
                    number_of_dependants=int(row['number_of_dependants']),
                    employment_type=row['employment_type'],
                    applicant_type=row['applicant_type'],
                    has_hecs=bool(row.get('has_hecs', 0)),
                    has_bankruptcy=bool(row.get('has_bankruptcy', 0)),
                    state=row.get('state', 'NSW'),
                    # Bureau features
                    num_credit_enquiries_6m=_safe_val(row, 'num_credit_enquiries_6m', int),
                    worst_arrears_months=_safe_val(row, 'worst_arrears_months', int),
                    num_defaults_5yr=_safe_val(row, 'num_defaults_5yr', int),
                    credit_history_months=_safe_val(row, 'credit_history_months', int),
                    total_open_accounts=_safe_val(row, 'total_open_accounts', int),
                    num_bnpl_accounts=_safe_val(row, 'num_bnpl_accounts', int),
                    # Behavioural features
                    is_existing_customer=bool(row.get('is_existing_customer', 0)),
                    savings_balance=_safe_val(row, 'savings_balance'),
                    salary_credit_regularity=_safe_val(row, 'salary_credit_regularity'),
                    num_dishonours_12m=_safe_val(row, 'num_dishonours_12m', int),
                    avg_monthly_savings_rate=_safe_val(row, 'avg_monthly_savings_rate'),
                    days_in_overdraft_12m=_safe_val(row, 'days_in_overdraft_12m', int),
                    # Macroeconomic context
                    rba_cash_rate=_safe_val(row, 'rba_cash_rate'),
                    unemployment_rate=_safe_val(row, 'unemployment_rate'),
                    property_growth_12m=_safe_val(row, 'property_growth_12m'),
                    consumer_confidence=_safe_val(row, 'consumer_confidence'),
                    # Application integrity
                    income_verification_gap=_safe_val(row, 'income_verification_gap'),
                    document_consistency_score=_safe_val(row, 'document_consistency_score'),
                )
                created_count += 1

            self.stdout.write(self.style.SUCCESS(f'Created {created_count} LoanApplication records across {len(customers)} customers'))

            # -------------------------------------------------------
            # Named demo scenarios: 6 realistic Australian applicants
            # that demonstrate key lending decision outcomes.
            # -------------------------------------------------------
            demo_scenarios = [
                {
                    'label': 'First Home Buyer Couple (Approved)',
                    'username': 'sarah_chen',
                    'annual_income': Decimal('152000.00'), 'credit_score': 810,
                    'loan_amount': Decimal('680000.00'), 'loan_term_months': 360,
                    'debt_to_income': Decimal('4.70'), 'employment_length': 6,
                    'purpose': 'home', 'home_ownership': 'rent', 'has_cosigner': False,
                    'property_value': Decimal('850000.00'), 'deposit_amount': Decimal('170000.00'),
                    'monthly_expenses': Decimal('3400.00'), 'existing_credit_card_limit': Decimal('10000.00'),
                    'number_of_dependants': 0, 'employment_type': 'payg_permanent',
                    'applicant_type': 'couple', 'has_hecs': True, 'has_bankruptcy': False, 'state': 'NSW',
                    'is_existing_customer': True, 'num_credit_enquiries_6m': 1,
                    'worst_arrears_months': 0, 'num_defaults_5yr': 0, 'credit_history_months': 72,
                    'total_open_accounts': 3, 'num_bnpl_accounts': 0,
                    'savings_balance': Decimal('45000.00'), 'salary_credit_regularity': 0.98,
                    'num_dishonours_12m': 0, 'avg_monthly_savings_rate': 0.15,
                    'days_in_overdraft_12m': 0,
                    'rba_cash_rate': 4.35, 'unemployment_rate': 4.1,
                    'property_growth_12m': 5.2, 'consumer_confidence': 82.5,
                    'income_verification_gap': 0.02, 'document_consistency_score': 0.97,
                },
                {
                    'label': 'Regional Upgrader (Approved)',
                    'username': 'liam_oconnor',
                    'annual_income': Decimal('185000.00'), 'credit_score': 890,
                    'loan_amount': Decimal('520000.00'), 'loan_term_months': 300,
                    'debt_to_income': Decimal('3.10'), 'employment_length': 12,
                    'purpose': 'home', 'home_ownership': 'mortgage', 'has_cosigner': False,
                    'property_value': Decimal('780000.00'), 'deposit_amount': Decimal('260000.00'),
                    'monthly_expenses': Decimal('3800.00'), 'existing_credit_card_limit': Decimal('15000.00'),
                    'number_of_dependants': 2, 'employment_type': 'payg_permanent',
                    'applicant_type': 'couple', 'has_hecs': False, 'has_bankruptcy': False, 'state': 'QLD',
                    'is_existing_customer': True, 'num_credit_enquiries_6m': 0,
                    'worst_arrears_months': 0, 'num_defaults_5yr': 0, 'credit_history_months': 180,
                    'total_open_accounts': 5, 'num_bnpl_accounts': 0,
                    'savings_balance': Decimal('95000.00'), 'salary_credit_regularity': 1.0,
                    'num_dishonours_12m': 0, 'avg_monthly_savings_rate': 0.22,
                    'days_in_overdraft_12m': 0,
                    'rba_cash_rate': 4.35, 'unemployment_rate': 4.1,
                    'property_growth_12m': 3.8, 'consumer_confidence': 82.5,
                    'income_verification_gap': 0.01, 'document_consistency_score': 0.99,
                },
                {
                    'label': 'Self-Employed Tradie (Borderline)',
                    'username': 'marco_rossi',
                    'annual_income': Decimal('135000.00'), 'credit_score': 760,
                    'loan_amount': Decimal('620000.00'), 'loan_term_months': 360,
                    'debt_to_income': Decimal('4.90'), 'employment_length': 5,
                    'purpose': 'home', 'home_ownership': 'rent', 'has_cosigner': False,
                    'property_value': Decimal('775000.00'), 'deposit_amount': Decimal('155000.00'),
                    'monthly_expenses': Decimal('3200.00'), 'existing_credit_card_limit': Decimal('12000.00'),
                    'number_of_dependants': 1, 'employment_type': 'self_employed',
                    'applicant_type': 'single', 'has_hecs': False, 'has_bankruptcy': False, 'state': 'VIC',
                    'is_existing_customer': False, 'num_credit_enquiries_6m': 3,
                    'worst_arrears_months': 0, 'num_defaults_5yr': 0, 'credit_history_months': 60,
                    'total_open_accounts': 4, 'num_bnpl_accounts': 1,
                    'savings_balance': Decimal('28000.00'), 'salary_credit_regularity': 0.75,
                    'num_dishonours_12m': 0, 'avg_monthly_savings_rate': 0.08,
                    'days_in_overdraft_12m': 5,
                    'rba_cash_rate': 4.35, 'unemployment_rate': 4.1,
                    'property_growth_12m': 4.5, 'consumer_confidence': 82.5,
                    'income_verification_gap': 0.12, 'document_consistency_score': 0.88,
                },
                {
                    'label': 'Young Casual Worker (Denied - tenure)',
                    'username': 'chloe_martin',
                    'annual_income': Decimal('52000.00'), 'credit_score': 710,
                    'loan_amount': Decimal('25000.00'), 'loan_term_months': 36,
                    'debt_to_income': Decimal('2.80'), 'employment_length': 0,
                    'purpose': 'personal', 'home_ownership': 'rent', 'has_cosigner': False,
                    'property_value': None, 'deposit_amount': None,
                    'monthly_expenses': Decimal('1800.00'), 'existing_credit_card_limit': Decimal('3000.00'),
                    'number_of_dependants': 0, 'employment_type': 'payg_casual',
                    'applicant_type': 'single', 'has_hecs': True, 'has_bankruptcy': False, 'state': 'VIC',
                    'is_existing_customer': False, 'num_credit_enquiries_6m': 2,
                    'worst_arrears_months': 0, 'num_defaults_5yr': 0, 'credit_history_months': 18,
                    'total_open_accounts': 2, 'num_bnpl_accounts': 2,
                    'savings_balance': Decimal('3500.00'), 'salary_credit_regularity': 0.55,
                    'num_dishonours_12m': 1, 'avg_monthly_savings_rate': 0.03,
                    'days_in_overdraft_12m': 12,
                    'rba_cash_rate': 4.35, 'unemployment_rate': 4.1,
                    'property_growth_12m': 4.5, 'consumer_confidence': 82.5,
                    'income_verification_gap': 0.08, 'document_consistency_score': 0.91,
                },
                {
                    'label': 'High-DTI Investor (Denied - APRA cap)',
                    'username': 'raj_patel',
                    'annual_income': Decimal('210000.00'), 'credit_score': 850,
                    'loan_amount': Decimal('1300000.00'), 'loan_term_months': 360,
                    'debt_to_income': Decimal('6.20'), 'employment_length': 15,
                    'purpose': 'home', 'home_ownership': 'mortgage', 'has_cosigner': False,
                    'property_value': Decimal('1625000.00'), 'deposit_amount': Decimal('325000.00'),
                    'monthly_expenses': Decimal('4500.00'), 'existing_credit_card_limit': Decimal('25000.00'),
                    'number_of_dependants': 3, 'employment_type': 'payg_permanent',
                    'applicant_type': 'couple', 'has_hecs': False, 'has_bankruptcy': False, 'state': 'NSW',
                    'is_existing_customer': True, 'num_credit_enquiries_6m': 4,
                    'worst_arrears_months': 0, 'num_defaults_5yr': 0, 'credit_history_months': 210,
                    'total_open_accounts': 8, 'num_bnpl_accounts': 0,
                    'savings_balance': Decimal('120000.00'), 'salary_credit_regularity': 1.0,
                    'num_dishonours_12m': 0, 'avg_monthly_savings_rate': 0.18,
                    'days_in_overdraft_12m': 0,
                    'rba_cash_rate': 4.35, 'unemployment_rate': 4.1,
                    'property_growth_12m': 5.2, 'consumer_confidence': 82.5,
                    'income_verification_gap': 0.01, 'document_consistency_score': 0.98,
                },
                {
                    'label': 'Bankruptcy Recovery (Denied - bankruptcy)',
                    'username': 'tom_anderson',
                    'annual_income': Decimal('78000.00'), 'credit_score': 620,
                    'loan_amount': Decimal('15000.00'), 'loan_term_months': 36,
                    'debt_to_income': Decimal('2.10'), 'employment_length': 3,
                    'purpose': 'personal', 'home_ownership': 'rent', 'has_cosigner': False,
                    'property_value': None, 'deposit_amount': None,
                    'monthly_expenses': Decimal('2200.00'), 'existing_credit_card_limit': Decimal('0.00'),
                    'number_of_dependants': 1, 'employment_type': 'payg_permanent',
                    'applicant_type': 'single', 'has_hecs': False, 'has_bankruptcy': True, 'state': 'SA',
                    'is_existing_customer': False, 'num_credit_enquiries_6m': 5,
                    'worst_arrears_months': 3, 'num_defaults_5yr': 2, 'credit_history_months': 48,
                    'total_open_accounts': 1, 'num_bnpl_accounts': 0,
                    'savings_balance': Decimal('2000.00'), 'salary_credit_regularity': 0.85,
                    'num_dishonours_12m': 2, 'avg_monthly_savings_rate': 0.02,
                    'days_in_overdraft_12m': 30,
                    'rba_cash_rate': 4.35, 'unemployment_rate': 4.1,
                    'property_growth_12m': 4.5, 'consumer_confidence': 82.5,
                    'income_verification_gap': 0.05, 'document_consistency_score': 0.82,
                },
            ]

            self.stdout.write('Creating named demo scenarios...')
            for scenario in demo_scenarios:
                user = CustomUser.objects.filter(username=scenario['username']).first()
                if not user:
                    continue
                fields = {k: v for k, v in scenario.items() if k not in ('label', 'username')}
                LoanApplication.objects.create(applicant=user, **fields)
                self.stdout.write(f'  Created: {scenario["label"]}')
