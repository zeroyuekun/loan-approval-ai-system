# Celery queue backpressure

**Severity:** Medium–High — applications submitted but decisions not rendering; users see "processing" for minutes.

## Symptoms

- Dashboard shows applications stuck at "scoring" / "generating email"
- `POST /applications/` returns 202 but the status endpoint never advances past "queued"
- Redis queue length grows faster than workers drain it

## Diagnose

1. **Queue depth per queue:**
   ```bash
   docker compose exec redis redis-cli -a "$REDIS_PASSWORD" LLEN celery
   docker compose exec redis redis-cli -a "$REDIS_PASSWORD" LLEN ml
   docker compose exec redis redis-cli -a "$REDIS_PASSWORD" LLEN agents
   docker compose exec redis redis-cli -a "$REDIS_PASSWORD" LLEN email
   ```

   Healthy: each < 50. Backpressure: growing monotonically.

2. **Worker heartbeat:**
   ```bash
   docker compose exec backend celery -A config inspect active --timeout 5
   docker compose exec backend celery -A config inspect stats --timeout 5
   ```

   If a worker doesn't respond, it's dead or stuck.

3. **Worker logs for OOM / unhandled exceptions:**
   ```bash
   docker compose logs --tail 500 celery_worker_ml
   docker compose logs --tail 500 celery_worker_agents
   ```

4. **Common causes (in order of frequency):**
   - Worker OOM killed by container (see frontend-exit-243 runbook for the memory-limit pattern)
   - Long-running task exceeding `task_soft_time_limit`
   - Redis password mismatch causing workers to silently drop
   - Dead-letter build-up (check `celery_results` table in Postgres)

## Remediate

**Clear backlog safely:**

1. Scale up workers temporarily:
   ```bash
   docker compose up -d --scale celery_worker_ml=3 --scale celery_worker_agents=2
   ```

2. If a specific task type is stuck, **do not blindly purge the queue** — purging loses applications. Instead:
   - `celery -A config inspect reserved` to see what's stuck
   - Identify the task IDs
   - Revoke only those: `celery -A config control revoke <task_id>`

3. Restart workers if their process heap looks bloated (RSS > 2x the average):
   ```bash
   docker compose restart celery_worker_ml
   ```
   Workers will re-consume from Redis; `task_acks_late=True` means in-flight tasks come back.

**Purge only in a dev environment.** In production, file an incident and drain manually.

## Escalate

- Attach: queue lengths (all queues, 3 readings 10 minutes apart), worker logs (500 lines each), Flower dashboard screenshot.
- Tag Backend + Infra owners.
- If P95 latency > 5 min for > 30 min: flip the "predictions-via-sync-fallback" feature flag (once implemented) so the API blocks on ML instead of queueing.
