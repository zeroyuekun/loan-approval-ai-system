import random

from django.core.management.base import BaseCommand

from apps.accounts.models import CustomUser
from apps.loans.models import LoanApplication
from apps.ml_engine.services.data_generator import DataGenerator


class Command(BaseCommand):
    help = 'Generate synthetic loan application data for model training'

    def add_arguments(self, parser):
        parser.add_argument(
            '--num-records', type=int, default=10000,
            help='Number of records to generate (default: 10000)',
        )
        parser.add_argument(
            '--output', type=str, default='.tmp/synthetic_loans.csv',
            help='Output CSV file path (default: .tmp/synthetic_loans.csv)',
        )
        parser.add_argument(
            '--create-db-records', type=int, default=100,
            help='Number of LoanApplication records to create in DB (default: 100)',
        )

    def handle(self, *args, **options):
        num_records = options['num_records']
        output_path = options['output']
        db_count = options['create_db_records']

        self.stdout.write(f'Generating {num_records} synthetic loan records...')

        generator = DataGenerator()
        df = generator.generate(num_records=num_records)
        generator.save_to_csv(df, output_path)

        self.stdout.write(self.style.SUCCESS(f'Saved {num_records} records to {output_path}'))

        # Create DB records for a subset
        if db_count > 0:
            self.stdout.write(f'Creating {db_count} LoanApplication records in DB...')

            # Ensure at least one customer user exists
            customer, created = CustomUser.objects.get_or_create(
                username='demo_customer',
                defaults={
                    'email': 'demo@example.com',
                    'role': 'customer',
                    'first_name': 'Demo',
                    'last_name': 'Customer',
                },
            )
            if created:
                customer.set_password('demo1234')
                customer.save()

            subset = df.sample(n=min(db_count, len(df)), random_state=42)
            created_count = 0
            for _, row in subset.iterrows():
                LoanApplication.objects.create(
                    applicant=customer,
                    annual_income=row['annual_income'],
                    credit_score=int(row['credit_score']),
                    loan_amount=row['loan_amount'],
                    loan_term_months=int(row['loan_term_months']),
                    debt_to_income=round(row['debt_to_income'], 4),
                    employment_length=int(row['employment_length']),
                    purpose=row['purpose'],
                    home_ownership=row['home_ownership'],
                    has_cosigner=bool(row['has_cosigner']),
                )
                created_count += 1

            self.stdout.write(self.style.SUCCESS(f'Created {created_count} LoanApplication records'))
