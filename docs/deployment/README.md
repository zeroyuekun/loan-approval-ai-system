# Deploying the Demo

This guide covers a **self-hosted** deploy: Vercel for the Next.js frontend and your choice of backend host for Django + Celery + PostgreSQL + Redis. There is no free public demo URL — host it yourself and point the frontend at your backend.

Target setup:
- **Frontend:** Vercel (free tier, `syd1` region for AU latency)
- **Backend:** any host that can run the `backend/` Dockerfile and a Celery worker (see alternatives below)
- **Data:** PostgreSQL (managed or self-hosted) and Redis (managed or self-hosted)

## Why not a free public demo?

A free always-on public demo of a full Django + Celery + PostgreSQL + Redis stack pushes past most platforms' free tiers — every option is either cold-start-heavy, bandwidth-capped, or charges for always-on workers. Rather than ship a brittle public URL that breaks when a trial expires, this guide documents how to self-host on whichever backend host suits you: **Render** (generous free web service, paid background workers), **Railway** ($5/month starter credit), **Koyeb** (free compute for one small service), or **Oracle Always Free** (2 ARM VMs, full root, no cold starts). Pick the one whose trade-offs you are happy with — every command below is host-agnostic except the frontend step.

---

## Prerequisites

```bash
# Vercel CLI for the frontend
npm i -g vercel
vercel login

# Docker + Docker Compose for local verification before deploying
docker --version
docker compose version
```

You will also need:
- A PostgreSQL 15+ connection string (`postgres://user:pass@host:5432/db`)
- A Redis 7+ connection string (`redis://host:6379/0`)
- An Anthropic API key (any budget works; the app caps spend to `ANTHROPIC_DAILY_BUDGET_USD`)

---

## Step 1 — Bring your own backend host

Pick a host that can run:
1. The Django web process (`gunicorn config.wsgi --bind 0.0.0.0:$PORT`)
2. A Celery worker (`celery -A config worker --concurrency=1`)
3. Optional: a Celery beat process (`celery -A config beat`) for scheduled tasks

### Minimum required environment

Copy `.env.example` to `.env` and set at least these keys on your host:

```bash
DJANGO_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(50))">
FIELD_ENCRYPTION_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
DATABASE_URL=postgres://...
REDIS_URL=redis://...
CELERY_BROKER_URL=${REDIS_URL}
ALLOWED_HOSTS=your-backend-host.example.com
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_DAILY_BUDGET_USD=1.00
DJANGO_SETTINGS_MODULE=config.settings.production
```

### Deploy shape (host-agnostic)

1. Build the backend Docker image from `backend/Dockerfile`.
2. Run `python manage.py migrate --noinput` on release.
3. Start the web process on the host's assigned port.
4. Start the Celery worker process (separate container / service).
5. One-off, after first deploy: run `python manage.py seed_demo` to create the admin user, 100 synthetic applicants, and the Neville Zeng golden fixture.

### Host-specific notes

| Host | Always-on | Free tier shape | Notes |
|---|---|---|---|
| Render | Web: yes (sleeps on free plan after 15min idle), Worker: paid | 750 free web hours/month, 90-day Postgres | Cold-start ~30s after sleep. Paid Starter = $7/mo keeps warm. |
| Railway | Yes while credits last | $5 starter credit, then pay-as-you-go | Simplest to deploy; cheapest once credits run out is ~$5/month for this stack. |
| Koyeb | Yes (one free small service) | 1 web service + 1 Postgres | Can run the web process free; Celery worker needs a paid plan. |
| Oracle Always Free | Yes | 2×ARM VMs, 24GB RAM total, no time limit | No managed DB — run Postgres + Redis on the same VMs. Hardest to set up, most capable once running. |

### Verify

```bash
curl -fsS https://your-backend-host.example.com/api/v1/health/
```

Expected: `200 OK` with a JSON health payload.

---

## Step 2 — Frontend on Vercel

```bash
cd frontend
vercel link

# Point the frontend at your backend
vercel env add NEXT_PUBLIC_API_URL production
# Enter: https://your-backend-host.example.com/api/v1

vercel env add NEXT_PUBLIC_ACL_NUMBER production
# Enter: DEMO-LENDER-000000   (or your real ACL if not a demo)

vercel --prod
```

The `deploy/vercel.json` at the repo root pins the build to `syd1` and sets placeholder env defaults — the `vercel env add` commands above override them for your deployment.

### Verify

- Open the Vercel deployment URL in a browser.
- Log in with the admin user created by `seed_demo` (username `admin`, password `demo-admin-password`). **Change this password immediately if the demo is public-facing.**
- Submit a new application, or view the Neville Zeng fixture in the officer dashboard.

---

## Cost and cold-start notes

- **Cold start:** expect ~10–30 s on the first request after idle if your backend host sleeps on free tier. Upgrade the backend plan or use Oracle Always Free if you need consistent sub-3 s latency.
- **Claude API:** `ANTHROPIC_DAILY_BUDGET_USD=1.00` caps daily spend — the in-app cost guard stops email generation if the cap is exceeded.
- **Bandwidth:** Vercel free tier is 100 GB/month; for a portfolio demo this is overkill.
- **Postgres:** a 100-applicant demo fits comfortably in 1 GB; 5 GB is plenty for the full synthetic dataset.

---

## Rollback

- **Frontend:** `vercel rollback` or revert via the Vercel dashboard.
- **Backend:** depends on host — Render has a "Rollback" button per deploy, Railway keeps snapshots, Koyeb serves the previous container until the new one is healthy, and Oracle is a manual `docker compose` revert.
- **Full teardown:** destroy the Vercel project and remove the backend host's deployment + managed DB.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Backend 502 on first curl | Cold start on free-tier host | Wait 20–30 s and retry, or upgrade the plan. |
| `/api/v1/health/` returns 500 | Migrations not run | Exec into the backend container and run `python manage.py migrate`. |
| Frontend shows CORS error | `NEXT_PUBLIC_API_URL` wrong or `CORS_ALLOWED_ORIGINS` missing the Vercel URL | Re-run `vercel env add` and set `CORS_ALLOWED_ORIGINS` on the backend to include the Vercel URL. |
| Celery worker not processing | Redis unreachable | Check `REDIS_URL` / `CELERY_BROKER_URL`; tail worker logs. |
| Login page loads but login fails | `seed_demo` not run | Exec into the backend container and run `python manage.py seed_demo`. |
