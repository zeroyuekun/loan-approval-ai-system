# Frontend container exits with code 243

**Severity:** High — end users can't reach the UI.

## Symptoms

- `docker compose ps frontend` shows `exited (243)` in a loop
- Browsers at port 3000 see "connection refused" or immediate 502
- Container restarts every 10–30 seconds

## Diagnose

1. **Get the last logs before the exit:**

   ```bash
   docker compose logs --tail 200 frontend
   ```

2. **Common signatures:**

   | Signature in logs | Likely cause |
   |-------------------|--------------|
   | `JavaScript heap out of memory` / `FATAL ERROR: Reached heap limit` | Node OOM during build or SSR |
   | `Error: listen EADDRINUSE` | Port conflict inside container |
   | `unable to resolve host` (for the backend) | Networking — `depends_on` or service name mismatch |
   | `health check failed` / no logs at all, just a restart | Healthcheck timing out before app is ready |
   | `kill -9` without message | OOM at container level (cgroup limit) |

3. **Check cgroup memory limit:**

   ```bash
   docker inspect $(docker compose ps -q frontend) --format '{{.HostConfig.Memory}}'
   ```

   Value `0` means no limit. A low limit (e.g. 134217728 = 128 MB) with a Next.js build will OOM every time.

4. **Exit code 243 specifically** usually means Node exited with code 115 (128+115 = 243). Common cause: Node hit its heap limit and exited.

## Remediate

**If OOM (most common):**

1. Edit `docker-compose.yml` frontend service:
   ```yaml
   services:
     frontend:
       deploy:
         resources:
           limits:
             memory: 1G
       environment:
         NODE_OPTIONS: "--max-old-space-size=768"
   ```

2. Rebuild + restart:
   ```bash
   docker compose up -d --build frontend
   docker compose logs -f frontend
   ```

**If healthcheck timeout:**

In the frontend service, extend `healthcheck.start_period`:
```yaml
healthcheck:
  start_period: 60s
  interval: 10s
  timeout: 5s
  retries: 5
```

**If networking:**

Confirm the backend hostname used by the frontend container matches the service name in compose. Run `docker compose exec frontend ping backend`.

## Escalate

If the container still crash-loops after applying the fix above:

- Attach to the escalation issue: full `docker compose logs frontend` output (at least 500 lines), `docker inspect frontend` JSON, and `docker stats frontend --no-stream`.
- Tag the Frontend and Infra owners from `.github/CODEOWNERS`.
- If production is affected: flip the "maintenance mode" feature flag (once implemented) or route DNS to a static status page.
