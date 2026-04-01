#!/usr/bin/env bash
set -euo pipefail

echo "Waiting for PostgreSQL to be ready..."

until pg_isready -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-postgres}" > /dev/null 2>&1; do
  echo "  PostgreSQL is not ready yet. Retrying in 2 seconds..."
  sleep 2
done

echo "PostgreSQL is ready."

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Creating superuser..."
if [ -z "$DJANGO_SUPERUSER_PASSWORD" ]; then
  echo "WARNING: DJANGO_SUPERUSER_PASSWORD not set — skipping superuser creation."
else
  python manage.py createsuperuser --noinput \
    --username "${DJANGO_SUPERUSER_USERNAME:-admin}" \
    --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" \
    || echo "Superuser already exists, skipping."
fi

echo "Database initialization complete."
