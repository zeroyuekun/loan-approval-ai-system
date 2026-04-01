#!/usr/bin/env bash
set -euo pipefail

echo "Running migrations..."
python manage.py migrate --noinput

# Ensure the admin account exists (only set password on first creation).
# Uses os.environ inside Python to avoid shell injection from special chars in passwords.
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    python manage.py shell -c "
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ['DJANGO_SUPERUSER_USERNAME']
u, created = User.objects.get_or_create(
    username=username,
    defaults={
        'email': os.environ.get('DJANGO_SUPERUSER_EMAIL', ''),
        'is_staff': True,
        'is_superuser': True,
        'role': 'admin',
    },
)
if created:
    u.set_password(os.environ['DJANGO_SUPERUSER_PASSWORD'])
    u.save()
    print(f'Admin account {username!r} created.')
else:
    print(f'Admin account {username!r} already exists — skipping password reset.')
"
fi

echo "Starting: $@"
exec "$@"
