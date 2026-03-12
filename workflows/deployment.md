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

### Port Conflicts

| Port | Service | Fix |
|------|---------|-----|
| 5432 | PostgreSQL | Stop local Postgres or change `POSTGRES_PORT` in `.env` and `docker-compose.yml` |
| 6379 | Redis | Stop local Redis or remap in `docker-compose.yml` |
| 8000 | Django | Change the backend port mapping in `docker-compose.yml` |
| 3000 | Next.js | Change the frontend port mapping in `docker-compose.yml` |

### Volume Permissions

If you see permission errors on mounted volumes:
```bash
# Reset volume permissions
docker-compose down -v
docker-compose up -d
```

Note: `-v` removes named volumes (including database data). Only use this for a fresh start.

### Database Connection Refused

```bash
# Check if db container is healthy
docker-compose ps db

# Check db logs
docker-compose logs db

# If the healthcheck is failing, wait 10-15 seconds and try again
# PostgreSQL may still be initializing
```

### Celery Worker Not Processing Tasks

```bash
# Check worker logs
docker-compose logs celery_worker

# Verify Redis is accessible
docker-compose exec redis redis-cli ping
# Should return: PONG

# Restart the worker
docker-compose restart celery_worker
```

### Backend Build Fails

```bash
# Check for pip dependency issues
docker-compose logs backend

# Rebuild without cache
docker-compose build --no-cache backend
```

### Frontend Cannot Reach Backend

- Verify `NEXT_PUBLIC_API_URL` is set correctly in `.env`
- Inside Docker network, frontend uses `http://backend:8000`, not `localhost`
- From the browser, API calls go to `http://localhost:8000/api/v1/`

## Stopping the System

```bash
# Stop all containers (preserves data)
docker-compose down

# Stop and remove all data (fresh start)
docker-compose down -v
```
