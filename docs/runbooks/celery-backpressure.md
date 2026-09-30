# Celery queue backpressure

**Severity:** Medium to high. Applications are submitted but decisions don't render, and users see "processing" for minutes.

## Symptoms

- Dashboard shows applications stuck at "scoring" / "generating email"
- `POST /applications/` returns 202 but the status endpoint never advances past "queued"
- Redis queue length grows faster than workers drain it

## Diagnose

1. **Check the depth of each queue:**
   ```bash
   docker compose exec redis redis-cli -a "$REDIS_PASSWORD" LLEN celery
   docker compose exec redis redis-cli -a "$REDIS_PASSWORD" LLEN ml
   docker compose exec redis redis-cli -a "$REDIS_PASSWORD" LLEN agents
   docker compose exec redis redis-cli -a "$REDIS_PASSWORD" LLEN email
   ```

   Healthy: each is below 50. Backpressure: the length grows monotonically.

2. **Check worker heartbeats:**
   ```bash
   docker compose exec backend celery -A config inspect active --timeout 5
   docker compose exec backend celery -A config inspect stats --timeout 5
   ```

   If a worker doesn't respond, it's dead or stuck.

3. **Check worker logs for OOM kills and unhandled exceptions:**
   ```bash
   docker compose logs --tail 500 celery_worker_ml
   docker compose logs --tail 500 celery_worker_agents
   ```

4. **Rule out the common causes, most frequent first:**
   - The container OOM-killed the worker (the frontend-exit-243 runbook covers the memory-limit pattern)
   - A long-running task exceeded `task_soft_time_limit`
   - A Redis password mismatch makes workers drop silently
   - Dead letters are building up (check the `celery_results` table in Postgres)

## Remediate

**Clear the backlog safely:**

1. Scale up workers temporarily:
   ```bash
   docker compose up -d --scale celery_worker_ml=3 --scale celery_worker_agents=2
   ```

2. If a specific task type is stuck, **do not blindly purge the queue**, because purging loses applications. Instead:
   - Run `celery -A config inspect reserved` to see what's stuck.
   - Identify the task IDs.
   - Revoke only those: `celery -A config control revoke <task_id>`

3. Restart workers if their process heap looks bloated (RSS > 2x the average):
   ```bash
   docker compose restart celery_worker_ml
   ```
   The workers re-consume from Redis. With `task_acks_late=True`, in-flight tasks come back.

**Purge only in a dev environment.** In production, file an incident and drain manually.

## Escalate

- Attach queue lengths (all queues, 3 readings 10 minutes apart), worker logs (500 lines each) and a Flower dashboard screenshot.
- Tag the Backend and Infra owners.
- If P95 latency stays above 5 min for more than 30 min, flip the "predictions-via-sync-fallback" feature flag (once implemented) so the API blocks on ML instead of queueing.
