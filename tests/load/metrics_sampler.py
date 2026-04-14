"""Side sampler for stack metrics during a Locust run.

Samples every 5 seconds:
- Celery queue depth (ml, email, agents) via Redis LLEN
- Postgres active connection count
- Docker stats (CPU, mem) per core container

Writes CSV to --out. Stop with Ctrl+C.
"""
import argparse
import csv
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone


REDIS_SERVICE = os.environ.get("LOAD_SAMPLER_REDIS_SERVICE", "redis")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
POSTGRES_SERVICE = os.environ.get("LOAD_SAMPLER_POSTGRES_SERVICE", "db")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "loan_approval")


def redis_llen(queue: str) -> int:
    cmd = ["docker", "compose", "exec", "-T", REDIS_SERVICE, "redis-cli"]
    if REDIS_PASSWORD:
        cmd += ["-a", REDIS_PASSWORD, "--no-auth-warning"]
    cmd += ["LLEN", queue]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip() or 0)
    except Exception:
        return -1


def pg_active_connections() -> int:
    try:
        out = subprocess.run(
            [
                "docker", "compose", "exec", "-T", POSTGRES_SERVICE,
                "psql", "-U", POSTGRES_USER, "-d", POSTGRES_DB,
                "-tAc", "SELECT count(*) FROM pg_stat_activity;",
            ],
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
