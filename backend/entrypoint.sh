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
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
User = get_user_model()
username = os.environ['DJANGO_SUPERUSER_USERNAME']
password = os.environ['DJANGO_SUPERUSER_PASSWORD']
fields = {
    'email': os.environ.get('DJANGO_SUPERUSER_EMAIL', ''),
    'is_staff': True,
    'is_superuser': True,
    'role': 'admin',
}
existing = User.objects.filter(username=username).first()
if existing:
    print(f'Admin account {username!r} already exists — skipping password reset.')
    # Sign-in is by email, so an admin created before that change, with no
    # email, could not sign in. Fill a blank email; never overwrite one.
    if not existing.email and fields['email']:
        existing.email = fields['email']
        existing.save(update_fields=['email'])
        print(f'Admin account {username!r}: email set from DJANGO_SUPERUSER_EMAIL.')
else:
    # The bootstrap admin gets the same password rules as every other account.
    # A weak password is refused (the server still starts) rather than crashing.
    try:
        validate_password(password, user=User(username=username, **fields))
    except ValidationError as exc:
        print(f'Admin account {username!r} NOT created: DJANGO_SUPERUSER_PASSWORD is too weak: ' + ' '.join(exc.messages))
    else:
        u = User(username=username, **fields)
        u.set_password(password)
        u.save()
        print(f'Admin account {username!r} created.')
"
fi

echo "Starting: $@"
exec "$@"
