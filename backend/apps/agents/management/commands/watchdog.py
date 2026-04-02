"""
Self-healing watchdog service.

Runs as a long-lived process that monitors system health and takes
automated remediation actions:

1. Health checks — polls /api/v1/health/deep/ and tracks consecutive failures
2. Celery healing — detects stuck/zombie tasks and revokes them
3. DB connection watchdog — terminates idle leaked connections

Usage:
    python manage.py watchdog
    python manage.py watchdog --interval 60   # check every 60s
"""

import logging
import signal
import sys
import time

import redis
import requests
from celery import Celery
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

logger = logging.getLogger("watchdog")


class Command(BaseCommand):
    help = "Run the self-healing watchdog service"

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=30,
            help="Seconds between health check cycles (default: 30)",
        )
        parser.add_argument(
            "--max-idle-conn-minutes",
            type=int,
            default=10,
            help="Kill DB connections idle longer than this (default: 10)",
        )
        parser.add_argument(
            "--max-consecutive-failures",
            type=int,
            default=3,
            help="Consecutive health failures before critical alert (default: 3)",
        )

    def handle(self, *args, **options):
        # Ensure watchdog logger outputs to stdout
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

        interval = options["interval"]
        self.max_idle_minutes = options["max_idle_conn_minutes"]
        self.max_failures = options["max_consecutive_failures"]
        self.consecutive_failures = 0
        self._running = True

        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

        logger.info(
            "Watchdog started: interval=%ds, max_idle_conn=%dm, failure_threshold=%d",
            interval,
            self.max_idle_minutes,
            self.max_failures,
        )

        while self._running:
            try:
                self._run_cycle()
            except Exception:
                logger.exception("Watchdog cycle failed unexpectedly")
            time.sleep(interval)

        logger.info("Watchdog stopped")

    def _shutdown(self, signum, frame):
        logger.info("Watchdog received signal %s, shutting down", signum)
        self._running = False

    def _run_cycle(self):
        """Run one full watchdog cycle."""
        self._check_health()
        self._heal_celery()
        self._watch_db_connections()
        logger.info("Cycle complete — status: %s", "healthy" if self.consecutive_failures == 0 else "degraded")

    # ------------------------------------------------------------------
    # 1. Health checks
    # ------------------------------------------------------------------

    def _check_health(self):
        """Poll the deep health endpoint and track failures."""
        backend_url = "http://backend:8000/api/v1/health/deep/"
        try:
            resp = requests.get(backend_url, timeout=10)
            data = resp.json()

            db_ok = data.get("database") == "ok"
            redis_ok = data.get("redis") == "ok"
            queue_status = data.get("celery_queue_status", "ok")

            if db_ok and redis_ok:
                if self.consecutive_failures > 0:
                    logger.info(
                        "Health recovered after %d consecutive failures",
                        self.consecutive_failures,
                    )
                self.consecutive_failures = 0
                self._record_health("healthy", data)
            else:
                self.consecutive_failures += 1
                logger.warning(
                    "Health degraded (failure %d/%d): db=%s redis=%s",
                    self.consecutive_failures,
                    self.max_failures,
                    data.get("database"),
                    data.get("redis"),
                )
                self._record_health("degraded", data)

            if queue_status == "critical":
                logger.warning("Celery queue depth critical: %s", data.get("celery_queue_depth"))

            if self.consecutive_failures >= self.max_failures:
                logger.critical(
                    "ALERT: %d consecutive health failures — system requires attention",
                    self.consecutive_failures,
                )

        except requests.RequestException as e:
            self.consecutive_failures += 1
            logger.error(
                "Health check unreachable (failure %d/%d): %s",
                self.consecutive_failures,
                self.max_failures,
                e,
            )
            self._record_health("unreachable", {"error": str(e)})

    def _record_health(self, status, details):
        """Store health state in Redis for observability."""
        try:
            r = redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=3)
            r.hset(
                "watchdog:health",
                mapping={
                    "status": status,
                    "consecutive_failures": str(self.consecutive_failures),
                    "last_check": timezone.now().isoformat(),
                    "db": str(details.get("database", "unknown")),
                    "redis": str(details.get("redis", "unknown")),
                },
            )
            r.expire("watchdog:health", 120)
        except Exception:
            pass  # Redis itself may be down

    # ------------------------------------------------------------------
    # 2. Self-healing Celery
    # ------------------------------------------------------------------

    def _heal_celery(self):
        """Detect and revoke stuck Celery tasks."""
        try:
            app = Celery("config")
            app.config_from_object("django.conf:settings", namespace="CELERY")
            inspect = app.control.inspect(timeout=5)

            active = inspect.active()
            if not active:
                logger.debug("No Celery workers responded to inspect")
                return

            now = time.time()
            default_time_limit = getattr(settings, "CELERY_TASK_TIME_LIMIT", 600)

            for worker_name, tasks in active.items():
                for task in tasks:
                    task_id = task.get("id")
                    task_name = task.get("name", "unknown")
                    started = task.get("time_start")

                    if not started:
                        continue

                    elapsed = now - started
                    time_limit = task.get("time_limit") or default_time_limit

                    # Task running longer than 2x its time limit is stuck
                    if elapsed > time_limit * 2:
                        logger.warning(
                            "Revoking stuck task %s (%s) on %s — running %.0fs (limit: %ds)",
                            task_id,
                            task_name,
                            worker_name,
                            elapsed,
                            time_limit,
                        )
                        app.control.revoke(task_id, terminate=True, signal="SIGKILL")
                        self._cleanup_stuck_task(task)

            # Check for reserved (prefetched) tasks that may be stuck
            reserved = inspect.reserved()
            if reserved:
                for worker_name, tasks in reserved.items():
                    if len(tasks) > 50:
                        logger.warning(
                            "Worker %s has %d reserved tasks — possible prefetch buildup",
                            worker_name,
                            len(tasks),
                        )

        except Exception as e:
            logger.debug("Celery inspection failed (workers may be down): %s", e)

    def _cleanup_stuck_task(self, task):
        """Clean up application state after revoking a stuck task."""
        try:
            task_name = task.get("name", "")
            args = task.get("args", [])

            # Only clean up orchestrator tasks that have an application_id
            if "orchestrate_pipeline" in task_name and args:
                application_id = args[0]
                from apps.agents.tasks import _cleanup_stuck_application

                _cleanup_stuck_application(application_id)
                logger.info("Cleaned up application %s after stuck task revocation", application_id)
        except Exception as e:
            logger.error("Failed to clean up after stuck task: %s", e)

    # ------------------------------------------------------------------
    # 3. Database connection watchdog
    # ------------------------------------------------------------------

    def _watch_db_connections(self):
        """Monitor and terminate leaked/idle database connections."""
        try:
            with connection.cursor() as cursor:
                # Get connection stats
                cursor.execute("""
                    SELECT
                        state,
                        count(*) as count,
                        max(extract(epoch from (now() - state_change)))::int as max_idle_seconds
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND pid != pg_backend_pid()
                    GROUP BY state
                """)
                stats = cursor.fetchall()

                total = 0
                for state, count, max_idle in stats:
                    total += count
                    if state == "idle" and max_idle and max_idle > self.max_idle_minutes * 60:
                        logger.info(
                            "DB connections: %d %s (longest idle: %ds)",
                            count,
                            state,
                            max_idle,
                        )

                # Terminate connections idle longer than threshold
                cursor.execute(
                    """
                    SELECT pid, usename, application_name,
                           extract(epoch from (now() - state_change))::int as idle_seconds
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND pid != pg_backend_pid()
                      AND state = 'idle'
                      AND state_change < now() - interval '%s minutes'
                    """,
                    [self.max_idle_minutes],
                )
                idle_connections = cursor.fetchall()

                for pid, user, app_name, idle_secs in idle_connections:
                    logger.info(
                        "Terminating idle DB connection: pid=%s user=%s app=%s idle=%ds",
                        pid,
                        user,
                        app_name,
                        idle_secs,
                    )
                    cursor.execute("SELECT pg_terminate_backend(%s)", [pid])

                if idle_connections:
                    logger.info("Terminated %d idle DB connections", len(idle_connections))

                # Log pool stats
                cursor.execute("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND pid != pg_backend_pid()
                """)
                active_count = cursor.fetchone()[0]

                # Get max connections
                cursor.execute("SHOW max_connections")
                max_conns = int(cursor.fetchone()[0])

                usage_pct = (active_count / max_conns) * 100
                if usage_pct > 80:
                    logger.warning(
                        "DB connection pool at %.0f%% (%d/%d)",
                        usage_pct,
                        active_count,
                        max_conns,
                    )
                elif usage_pct > 50:
                    logger.info(
                        "DB connections: %d/%d (%.0f%%)",
                        active_count,
                        max_conns,
                        usage_pct,
                    )

        except Exception as e:
            logger.error("DB connection watchdog failed: %s", e)
        finally:
            # Clean up Django's own stale connections
            from django.db import close_old_connections

            close_old_connections()
