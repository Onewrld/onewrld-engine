"""Worker: the loop that takes jobs off the queue and runs them.

It is always BOUNDED: it stops after `max_jobs` jobs or `max_seconds` seconds, whichever
comes first, or as soon as the kill switch turns on. A scheduler (Phase 5) starts it on a
timer; nothing ever runs forever.
"""

from __future__ import annotations

import os
import socket
import time
from collections import Counter

import onewrld.handlers  # noqa: F401  (registers all job handlers)
from onewrld import db, jobs, notify, safety
from onewrld.config import Settings
from onewrld.logging_setup import get_logger

log = get_logger(__name__)


def run_worker(settings: Settings, max_jobs: int = 25, max_seconds: int = 300) -> Counter:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    deadline = time.monotonic() + max_seconds
    stats: Counter = Counter()

    with db.connect(settings) as conn:
        jobs.requeue_stale(conn)
        while stats.total() < max_jobs and time.monotonic() < deadline:
            if safety.is_halted(settings):
                log.warning("Worker stopping: kill switch is on")
                stats["stopped_by_kill_switch"] += 1
                break
            with conn.transaction():
                job = jobs.claim(conn, worker_id)
            if job is None:
                break  # queue empty
            stats[jobs.run_one(settings, conn, job)] += 1

        # Email any new warn/critical alerts (bundled and capped; see notify.py).
        try:
            outcome = notify.flush_alert_emails(settings, conn)
            if outcome not in ("nothing", "not_configured"):
                log.info(f"Alert email: {outcome}")
        except Exception as e:
            log.error(f"Alert email step failed: {e}")

    log.info(f"Worker finished: {dict(stats)}", extra={"fields": {"event": "worker_done"}})
    return stats
