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

## Scope: local-only portfolio project

This project is designed to run locally via Docker Compose. No cloud-hosting configuration is committed. That is a deliberate scoping choice — portfolio reviewers are expected to clone, `make dev`, and walk through the dashboards on `localhost`.

Operational procedures for a running local instance (rotating secrets, recovering from a stuck Celery queue, database backup, upgrading the model) live in `backend/docs/RUNBOOK.md`. Security and compliance baselines live in `backend/docs/SECURITY.md`.

If you need a cloud deployment of your own, the Docker Compose topology is portable to any container host (Kubernetes, bare-metal, or any PaaS that accepts Docker images) — but no specific host config is supported here.
