"""Side sampler for stack metrics during a Locust run.

Samples every 5 seconds:
- Celery queue depth (ml, email, agents) via Redis LLEN
- Postgres active connection count
- Docker stats (CPU, mem) per core container

Writes CSV to --out. Stop with Ctrl+C.
"""
import argparse
import csv
import shutil
import subprocess
import time
from datetime import datetime, timezone


def redis_llen(queue: str) -> int:
    try:
        out = subprocess.run(
            ["docker", "compose", "exec", "-T", "redis", "redis-cli", "LLEN", queue],
            capture_output=True, text=True, timeout=5,
        )
        return int(out.stdout.strip() or 0)
    except Exception:
        return -1


def pg_active_connections() -> int:
    try:
        out = subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres",
             "-tAc", "SELECT count(*) FROM pg_stat_activity;"],
            capture_output=True, text=True, timeout=5,
        )
        return int(out.stdout.strip() or 0)
    except Exception:
        return -1


def docker_stats() -> dict[str, tuple[str, str]]:
    if not shutil.which("docker"):
        return {}
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return {}
    stats = {}
    for line in out.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) == 3:
            stats[parts[0]] = (parts[1], parts[2])
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "ts_utc", "ml_q", "email_q", "agents_q", "pg_conns", "docker_stats_json",
        ])
        try:
            while True:
                ts = datetime.now(timezone.utc).isoformat()
                ml = redis_llen("ml")
                em = redis_llen("email")
                ag = redis_llen("agents")
                pg = pg_active_connections()
                ds = docker_stats()
                w.writerow([ts, ml, em, ag, pg, str(ds)])
                f.flush()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
