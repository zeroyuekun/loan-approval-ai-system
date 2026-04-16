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

## Cloud Deployment Options

The project runs locally via Docker Compose as described above. A hosted demo URL is the single highest-impact portfolio polish item — without one, a reviewer can't try the product in a browser.

Picking a host is a tradeoff across cost, data residency, cold-start latency, and complexity. Three realistic paths:

| Host | Monthly cost (demo scale) | AU region | Cold-start | Complexity | Notes |
|---|---|---|---|---|---|
| **Fly.io** | $0 (free tier + ~$3 if exceeded) | Yes (`syd`) | ~10-20s on shared-cpu-1x | Medium | Best AU data residency. Needs `fly.toml` + `flyctl`. Backend + DB + Redis + Celery worker as separate processes. |
| **Render** | $0 (free web service + $7 paid DB) | No (closest: Singapore) | ~30-50s on free tier | Low | Friendliest setup via `render.yaml` + GitHub connect. Free tier sleeps after 15 min idle. |
| **Hetzner VPS** | ~€4.5/mo ($5) CX11 instance | EU only | None (always on) | High | Cheapest always-on. Requires self-managed Docker host + reverse proxy + TLS (Caddy or Traefik). |

The **frontend** (Next.js) deploys separately via Vercel free tier in all three scenarios — build Vercel on top of whichever backend host you pick, point `NEXT_PUBLIC_API_URL` at the backend URL.

### Required secrets (any host)

- `DJANGO_SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- `FIELD_ENCRYPTION_KEY` — generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `ANTHROPIC_API_KEY` — from console.anthropic.com
- `DATABASE_URL` + `REDIS_URL` — provided by the host's managed services
- `ALLOWED_HOSTS` — set to your deployed backend hostname
- `CORS_ALLOWED_ORIGINS` — set to your Vercel frontend URL

### Before deploying (any host)

- [ ] `.env.example` has no real secrets committed
- [ ] Backend image rebuilds cleanly: `docker compose build backend`
- [ ] Frontend builds cleanly: `cd frontend && npm run build`
- [ ] Migrations run cleanly against a fresh Postgres: `docker compose exec backend python manage.py migrate`
- [ ] Generate synthetic applicants: `docker compose exec backend python manage.py generate_data --count 100`
- [ ] Smoke test: `curl -fsS http://localhost:8000/api/v1/health/`

### Non-demo considerations (out of scope for portfolio)

Real production would need: Sentry DSN, a proper domain + TLS, CDN for frontend assets, background task monitoring (Flower or equivalent), database backups, rate limiting at the edge, and SR 11-7 / APRA CPS 234 compliance controls. The portfolio demo intentionally skips these — `backend/docs/SECURITY.md` covers the security baseline; regulatory/compliance control mapping is a future doc.
