# Deployment Workflow

## Objective

Stand up the full Loan Approval AI System locally using Docker Compose, including the Django backend, PostgreSQL, Redis, Celery workers, and the Next.js frontend.

## Prerequisites

- Docker and Docker Compose installed
- Git repository cloned
- At minimum 4GB RAM available for Docker

## Steps

### 1. Configure Environment

```bash
# Copy the example env file
cp .env.example .env

# Edit .env and fill in required values:
# - DJANGO_SECRET_KEY: Generate a random key (e.g., python -c "import secrets; print(secrets.token_urlsafe(50))")
# - ANTHROPIC_API_KEY: Your Claude API key from console.anthropic.com
# - Leave database and Redis defaults unless you have port conflicts
```

Required keys to set:
| Variable | Notes |
|----------|-------|
| `DJANGO_SECRET_KEY` | Must be unique, random, and secret |
| `ANTHROPIC_API_KEY` | Required for email generation and bias detection (Levels 2 and 3) |

### 2. Build Containers

```bash
docker-compose build
```

Expected: All 5 services build successfully (db, redis, backend, celery_worker, celery_beat, frontend).

### 3. Start Services

```bash
docker-compose up -d
```

Verify all containers are running:
```bash
docker-compose ps
```

All services should show `Up` status. The `db` and `redis` services should show `(healthy)`.

### 4. Run Migrations

```bash
docker-compose exec backend python manage.py migrate
```

### 5. Create Superuser

```bash
docker-compose exec backend python manage.py createsuperuser
```

Follow the prompts to set username, email, and password.

### 6. Generate Synthetic Data

```bash
# Option A: Using the standalone tool (outside Docker)
python tools/generate_synthetic_data.py --num-records 10000 --output-path .tmp/synthetic_loans.csv

# Option B: Using Django management command (inside Docker)
docker-compose exec backend python manage.py generate_loan_data --count 10000
```

### 7. Train Initial Model

```bash
# Option A: Using the standalone tool (outside Docker)
python tools/train_model.py --data-path .tmp/synthetic_loans.csv --algorithm both --output-dir backend/ml_models

# Option B: Using Django management command (inside Docker)
docker-compose exec backend python manage.py train_model --algorithm both
```

### 8. Verify

- Backend API: http://localhost:8000/api/v1/
- Django Admin: http://localhost:8000/admin/
- Frontend: http://localhost:3000
- Test Claude API: `python tools/test_claude_api.py`

## Troubleshooting

### Things that go wrong

Port conflicts are the most common issue. If 5432, 6379, 8000, or 3000 are already in use, either stop the local service or remap the port in `docker-compose.yml` (and `.env` for Postgres). The backend and frontend ports are the ones most likely to collide if you're running other dev servers.

Volume permission errors happen occasionally on Linux — `docker-compose down -v` then `up -d` fixes it, but `-v` nukes your database volumes so only do this when you want a fresh start.

PostgreSQL sometimes takes 10-15 seconds to initialise. If the backend can't connect, check `docker-compose ps db` and wait for the healthcheck to pass before panicking. Same goes for Celery workers — if tasks aren't processing, check `docker-compose logs celery_worker` and verify Redis is up (`docker-compose exec redis redis-cli ping` should return PONG).

Build failures are usually pip dependency issues. `docker-compose build --no-cache backend` is the nuclear option but it works.

<!-- the frontend→backend connection trips people up because inside Docker it's http://backend:8000, but from the browser it's localhost:8000 -->
If the frontend can't reach the backend, check `NEXT_PUBLIC_API_URL` in `.env`. Inside the Docker network the frontend talks to `http://backend:8000`, but from the browser API calls go to `http://localhost:8000/api/v1/`.

## Stopping the System

```bash
# Stop all containers (preserves data)
docker-compose down

# Stop and remove all data (fresh start)
docker-compose down -v
```

## Production deploy: Railway

Railway is the recommended target for a skimmable portfolio demo. It runs full containers with managed Postgres, managed Redis, and persistent volumes — no serverless refactor needed.

### Architecture on Railway

Four services in one Railway project:

| Service | Source | Notes |
|---|---|---|
| `backend` | `backend/Dockerfile` | Runs Django + Celery worker (single process for demo simplicity) |
| `frontend` | `frontend/Dockerfile` | Needs `NEXT_PUBLIC_API_URL` as a **build arg**, not a runtime var |
| `postgres` | Railway managed plugin | Injects `DATABASE_URL` automatically |
| `redis` | Railway managed plugin | Injects `REDIS_URL` automatically |

Backend settings already handle both `DATABASE_URL` and `REDIS_URL` with fallback — see `backend/config/settings/base.py`.

### Why a persistent volume for ML models

Model artifacts (`ml_models/*.joblib`) are saved to filesystem at training time and loaded at prediction time. Container restarts on ephemeral hosts would lose them.

**Fix**: mount a Railway persistent volume at `/app/ml_models` on the backend service. Zero code changes, tens of MB of storage, ~$0.25/GB/mo. Simpler than object storage for this workload. (Cloudflare R2 / django-storages was considered and rejected: added dependency, fragile secret management, and the "portability" benefit is imaginary for a portfolio project.)

### Secrets checklist

Set these in the Railway dashboard for the backend service:

| Variable | Required | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | yes | 50+ chars, random |
| `DJANGO_SETTINGS_MODULE` | yes | `config.settings.production` |
| `ANTHROPIC_API_KEY` | yes | For Claude email generation + compliance review |
| `FIELD_ENCRYPTION_KEY` | yes | Fernet key, see `SECRETS_ROTATION.md` for generation |
| `ALLOWED_HOSTS` | yes | Comma-separated, e.g. `api.example.com,backend.up.railway.app` |
| `CORS_ALLOWED_ORIGINS` | yes | Frontend origin(s), e.g. `https://app.example.com` |
| `EMAIL_HOST_PASSWORD` | conditional | Only if SMTP is wired up (otherwise template-only mode) |
| `SENTRY_DSN` | optional | Error tracking |
| `DATABASE_URL` | auto | Injected by the Postgres plugin |
| `REDIS_URL` | auto | Injected by the Redis plugin |

Frontend service only needs the build arg (see next section).

### NEXT_PUBLIC_API_URL must be a build arg, not a runtime var

**This is the most common footgun.** Next.js bakes `NEXT_PUBLIC_*` variables into the client bundle at build time. If Railway only sets it as a runtime env var, the deployed frontend still points at the `http://localhost:8000/api/v1` default baked at image build.

Configure the frontend service's build command (Railway dashboard → Settings → Build):

```
docker build --build-arg NEXT_PUBLIC_API_URL=https://<backend-domain>/api/v1 .
```

Or set it in the service's **Build Arguments** section, which Railway passes as Docker `--build-arg` automatically.

Verify after deploy by viewing page source — you should see the real backend URL, not `localhost:8000`, in the fetched JS bundles.

### Cost + rate-limit posture (skimmable preview)

This is a portfolio demo, not a production tenant. Keep spend low:

- Railway Hobby tier (~$5/mo credits) covers everything
- The existing `$5/day` Claude budget cap in ADR-006 survives to production via the `ApiBudgetGuard` — verify it's active in `production.py`
- DRF throttles in `base.py` are `20/min anon, 60/min user` — tighten if you see abuse
- Keep demo credentials pinned in README with a "demo-only, reset daily" label; optionally schedule a Railway cron to reset the DB overnight

### First deploy steps

1. Create Railway project, link the GitHub repo
2. Add Postgres and Redis managed plugins
3. Create the backend service from `backend/Dockerfile`, mount a volume at `/app/ml_models`
4. Create the frontend service from `frontend/Dockerfile`, set the `NEXT_PUBLIC_API_URL` build arg to the backend's public domain
5. Set backend env vars from the table above
6. Push to `main` — Railway builds and deploys both services
7. SSH into the backend service or run `railway run -- python manage.py migrate` locally
8. Seed an admin user: `railway run -- python manage.py createsuperuser --noinput` (requires `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` set as env vars)
9. Train an initial model: `railway run -- python manage.py train_model --algorithm xgb --data-path .tmp/synthetic_loans.csv` (may need to generate data first)
10. Smoke test: open the frontend URL, log in, submit an application, run the agent pipeline end-to-end

### Smoke test checklist

After first deploy, verify the full happy path:

- [ ] Frontend loads at the Railway public URL (HTTP 200)
- [ ] Login with demo credentials succeeds and sets the HttpOnly JWT cookie
- [ ] Submitting a new application returns a 201 and an application ID
- [ ] ML prediction runs and returns a probability + SHAP values
- [ ] Email generation runs and the guardrail layer passes
- [ ] Bias detection runs and scores the email
- [ ] NBO generates alternative offers for a denied application
- [ ] The watchdog container is running and healthy
- [ ] `/api/v1/ml/models/active/metrics/` returns the trained model card
