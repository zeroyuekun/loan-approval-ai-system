# Secrets Rotation Runbook

Last updated: 2026-03-30

---

## Quick Reference

| Secret | Protects | Rotation Frequency | Downtime Required |
|--------|----------|--------------------|-------------------|
| `DJANGO_SECRET_KEY` | Session cookies, JWT signing, CSRF tokens | 90 days | Brief (rolling restart) |
| `FIELD_ENCRYPTION_KEY` | PII at rest (ID numbers) | 180 days or on compromise | None (online rotation) |
| `ANTHROPIC_API_KEY` | Claude API access (email gen, bias detection) | 90 days | None (hot swap) |
| `POSTGRES_PASSWORD` | Database access | 90 days | Brief (rolling restart) |
| `REDIS_PASSWORD` | Celery broker, cache | 90 days | Brief (rolling restart) |
| `EMAIL_HOST_PASSWORD` | Gmail SMTP (app password) | 180 days | None (hot swap) |

---

## 1. DJANGO_SECRET_KEY

**What it protects:** Django session signing, CSRF token generation, and SimpleJWT token signing (JWT uses `SECRET_KEY` as the default `SIGNING_KEY`).

**Rotation procedure:**

1. Generate a new key:
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```
2. Update `DJANGO_SECRET_KEY` in `.env` on all hosts.
3. Restart all Django/Gunicorn and Celery workers (rolling restart is fine).

**What breaks on rotation:**
- All existing Django sessions are invalidated (admin users are logged out).
- All outstanding JWT access and refresh tokens become invalid (frontend users must re-authenticate).
- CSRF tokens in any open browser forms become invalid.

**Minimising impact:**
- Rotate during low-traffic periods.
- The frontend uses HttpOnly cookie-based JWT with 60-min access / 7-day refresh tokens. Users will need to log in again. There is no dual-key support for `SECRET_KEY` -- it is a hard cut-over.

**Rollback:** Revert `DJANGO_SECRET_KEY` to the previous value in `.env` and restart. Old sessions and JWTs will work again (if they have not expired).

---

## 2. FIELD_ENCRYPTION_KEY (Fernet)

**What it protects:** PII fields encrypted at rest in `CustomerProfile`: `primary_id_number`, `secondary_id_number`.

**Rotation procedure (zero-downtime):**

1. Generate a new Fernet key:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. Prepend the new key to `FIELD_ENCRYPTION_KEY`, comma-separated:
   ```
   FIELD_ENCRYPTION_KEY=NEW_KEY,OLD_KEY
   ```
   The encryption module (`apps.accounts.utils.encryption`) uses `MultiFernet` -- the first key encrypts, all keys decrypt.
3. Deploy the updated `.env` and restart Django/Celery workers.
4. Run the management command to re-encrypt all records with the new key:
   ```bash
   python manage.py rotate_encryption_key
   ```
   This iterates all `CustomerProfile` rows (chunked at 100), decrypts with any available key, and re-encrypts with the primary (first) key.
5. After confirming success (check command output for count), remove the old key:
   ```
   FIELD_ENCRYPTION_KEY=NEW_KEY
   ```
6. Restart workers again.

**What breaks on rotation:**
- If you replace the key without the comma-separated transition period, existing encrypted values become unreadable. The `decrypt_field` function degrades gracefully (returns the raw ciphertext), but PII will display as garbage.
- If you remove the old key before running `rotate_encryption_key`, any rows not yet re-encrypted will be unreadable.

**Rollback:** Add the old key back to the comma-separated list and restart. No data is lost as long as you still have the old key.

---

## 3. ANTHROPIC_API_KEY

**What it protects:** Access to the Claude API for email generation (`email_engine`), bias detection, NBO, and marketing agent (`agents`).

**Rotation procedure:**

1. Generate a new API key in the [Anthropic Console](https://console.anthropic.com/).
2. Update `ANTHROPIC_API_KEY` in `.env`.
3. Restart Celery workers on the `email` and `agents` queues. Django web workers also need restart if they read the key at import time.
4. Revoke the old key in the Anthropic Console.

**What breaks on rotation:**
- Any in-flight Celery tasks using the old key will fail with a 401 error. The orchestrator pipeline will record these as failed `AgentRun` records. They can be retried.
- The AI circuit breaker (`AI_CIRCUIT_BREAKER_THRESHOLD=3`) will trip after 3 consecutive failures, blocking new AI calls for 10 minutes. Plan the restart to minimise the window.

**Rollback:** If the new key is invalid, revert to the old key in `.env` and restart. Only revoke the old key in the Anthropic Console after confirming the new key works.

**Cost note:** Rotating the key does not affect the `$5/day` budget cap (`AI_DAILY_BUDGET_LIMIT_USD`). The budget counter resets daily regardless of key changes.

---

## 4. POSTGRES_PASSWORD

**What it protects:** Database authentication for the `loan_approval` PostgreSQL database.

**Rotation procedure:**

1. Set the new password in PostgreSQL:
   ```sql
   ALTER USER postgres WITH PASSWORD 'new-secure-password';
   ```
2. Update `POSTGRES_PASSWORD` in `.env` on all hosts.
3. Restart all Django/Gunicorn and Celery workers.

**What breaks on rotation:**
- If you change the DB password before updating `.env`, all application connections fail immediately. Django uses `CONN_MAX_AGE=600` with `CONN_HEALTH_CHECKS=True`, so stale connections will be detected and fail on the next request.
- Database migrations (`manage.py migrate`) will fail until the password is updated.

**Rollback:** Revert the PostgreSQL password:
```sql
ALTER USER postgres WITH PASSWORD 'old-password';
```

**Recommended approach for zero-downtime:**
1. Create a second PostgreSQL user with the same privileges.
2. Switch the application to the new user.
3. Drop the old user.
4. On next rotation, reverse the process.

---

## 5. REDIS_PASSWORD

**What it protects:** Celery broker (task queue), Django cache (DB 1), and Celery result backend connections.

**Rotation procedure:**

1. Set the new password in Redis:
   ```bash
   redis-cli CONFIG SET requirepass "new-password"
   ```
   Note: This is runtime-only. Also update `redis.conf` for persistence across Redis restarts.
2. Authenticate the current session with the new password:
   ```bash
   redis-cli AUTH "new-password"
   ```
3. Update `.env`:
   ```
   REDIS_PASSWORD=new-password
   CELERY_BROKER_URL=redis://:new-password@redis:6379/0
   ```
4. Restart all Django and Celery workers.

**What breaks on rotation:**
- All Celery workers lose broker connectivity. Tasks in the queue are not lost (Redis persists them), but no new tasks will be picked up until workers reconnect with the new password.
- Django cache reads/writes fail until restart. Cache misses degrade to DB queries.
- In-progress Celery tasks will complete but may fail to store results.

**Rollback:** Revert the Redis password with `CONFIG SET requirepass "old-password"` and restart workers.

---

## 6. EMAIL_HOST_PASSWORD (Gmail App Password)

**What it protects:** SMTP authentication for sending loan decision emails via Gmail (`smtp.gmail.com:587`).

**Rotation procedure:**

1. Generate a new app password in [Google Account Security](https://myaccount.google.com/apppasswords) for the `EMAIL_HOST_USER` account.
2. Update `EMAIL_HOST_PASSWORD` in `.env`.
3. Restart Celery workers on the `email` queue (and Django web workers).
4. Revoke the old app password in Google Account Security.

**What breaks on rotation:**
- Email sending fails with SMTP authentication errors. The template fallback system (`email_engine.services.template_fallback`) will still generate email content, but delivery will fail.
- Queued email tasks in Celery will fail and can be retried after the new password is active.

**Rollback:** Revert to the old app password in `.env` (if not yet revoked in Google) and restart.

---

## General Rotation Checklist

1. **Before rotation:** Back up the current `.env` file.
2. **Test the new credential** in a staging environment or with a quick smoke test before deploying to production.
3. **Restart order:** Web workers first, then Celery workers (`ml`, `email`, `agents` queues).
4. **Verify after rotation:**
   - Hit `/health/ready/` to confirm the app is up.
   - Trigger a test loan pipeline to verify Claude API, email sending, and DB access.
   - Check Celery worker logs for connection errors.
5. **Audit:** Record the rotation date and who performed it. Update any shared password managers.
6. **Never commit secrets** to git. Secrets live in `.env` only (see `CLAUDE.md` conventions).
