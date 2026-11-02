"""Job queue: a to-do list of background work, stored in the `job` table.

Lifecycle of a job:
  queued  -> waiting for its run_after time
  running -> a worker has claimed it (locked_at / locked_by are set)
  done    -> finished successfully
  dead    -> gave up (permanent error, or ran out of retries). An alert is raised.
             This is the "dead-letter queue": failed work parked for a human to look at.

Key guarantees:
- Idempotent enqueue: the same idempotency_key can only ever be queued once.
- Safe claiming: `FOR UPDATE SKIP LOCKED` means two workers can never grab the same job.
- Backoff: retryable failures wait longer each time (30s, 60s, 120s ... max 1h).
- Crash recovery: a job stuck in 'running' for too long is put back in the queue.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any, Callable

import psycopg
from psycopg.types.json import Jsonb

from onewrld.alerts import raise_alert
from onewrld.config import Settings
from onewrld.errors import HaltedError, PermanentError, RetryableError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)

BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 3600
STALE_AFTER = timedelta(minutes=30)
HALT_DELAY = timedelta(minutes=5)

# kind -> function(settings, payload) -> result (a dict, or None)
Handler = Callable[[Settings, dict], Any]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str):
    """Decorator that registers a function as the code that runs jobs of this kind."""
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return register


def enqueue(
    conn: psycopg.Connection,
    kind: str,
    payload: dict,
    idempotency_key: str,
    delay: timedelta | None = None,
    max_attempts: int = 5,
) -> tuple[int, bool]:
    """Add a job. Returns (job_id, created). created=False means it already existed,
    so nothing new was added."""
    row = conn.execute(
        """INSERT INTO job (kind, payload, idempotency_key, max_attempts, run_after)
           VALUES (%s, %s, %s, %s, now() + %s)
           ON CONFLICT (idempotency_key) DO NOTHING
           RETURNING id""",
        (kind, Jsonb(payload), idempotency_key, max_attempts, delay or timedelta(0)),
    ).fetchone()
    if row:
        return row["id"], True
    existing = conn.execute(
        "SELECT id FROM job WHERE idempotency_key = %s", (idempotency_key,)
    ).fetchone()
    return existing["id"], False


def backoff_seconds(attempt: int) -> int:
    """Wait time before retry number `attempt` (1-based), with +/-20% jitter so many failed
    jobs don't all retry at the same instant."""
    base = min(BASE_BACKOFF_SECONDS * 2 ** (attempt - 1), MAX_BACKOFF_SECONDS)
    return int(base * random.uniform(0.8, 1.2))


def claim(conn: psycopg.Connection, worker_id: str,
          only_ids: list[int] | None = None) -> dict | None:
    """Take the next runnable job, or None if there isn't one.
    only_ids limits the worker to specific jobs (e.g. the renders you just asked for),
    so unrelated jobs waiting in the queue can't use up its budget (M-008)."""
    return conn.execute(
        """UPDATE job SET status = 'running', locked_at = now(), locked_by = %s,
                          attempts = attempts + 1, updated_at = now()
           WHERE id = (
               SELECT id FROM job
               WHERE status = 'queued' AND run_after <= now()
                 AND (%s::bigint[] IS NULL OR id = ANY(%s::bigint[]))
               ORDER BY run_after, id
               FOR UPDATE SKIP LOCKED
               LIMIT 1)
           RETURNING *""",
        (worker_id, only_ids, only_ids),
    ).fetchone()


def requeue_stale(conn: psycopg.Connection) -> int:
    """Put back jobs whose worker crashed mid-run (running for longer than STALE_AFTER)."""
    cur = conn.execute(
        """UPDATE job SET status = 'queued', locked_at = NULL, locked_by = NULL,
                          last_error = 'requeued: worker stopped mid-run', updated_at = now()
           WHERE status = 'running' AND locked_at < now() - %s""",
        (STALE_AFTER,),
    )
    if cur.rowcount:
        log.warning(f"Requeued {cur.rowcount} stale job(s)")
    return cur.rowcount


def _finish(conn, job_id: int, result: Any) -> None:
    conn.execute(
        """UPDATE job SET status = 'done', result = %s, finished_at = now(),
                          locked_at = NULL, locked_by = NULL, updated_at = now()
           WHERE id = %s""",
        (Jsonb(result if isinstance(result, dict) else {"value": result}), job_id),
    )


def _retry_or_bury(conn, job: dict, exc: Exception, retryable: bool) -> str:
    error = f"{type(exc).__name__}: {exc}"[:2000]
    if retryable and job["attempts"] < job["max_attempts"]:
        wait = backoff_seconds(job["attempts"])
        conn.execute(
            """UPDATE job SET status = 'queued', run_after = now() + make_interval(secs => %s),
                              last_error = %s, error_class = %s, locked_at = NULL,
                              locked_by = NULL, updated_at = now()
               WHERE id = %s""",
            (wait, error, type(exc).__name__, job["id"]),
        )
        log.warning(f"Job {job['id']} ({job['kind']}) failed, retry in {wait}s: {error}")
        return "retrying"
    conn.execute(
        """UPDATE job SET status = 'dead', last_error = %s, error_class = %s,
                          finished_at = now(), locked_at = NULL, locked_by = NULL,
                          updated_at = now()
           WHERE id = %s""",
        (error, type(exc).__name__, job["id"]),
    )
    raise_alert(conn, "warn", f"job:{job['kind']}",
                f"Job {job['id']} failed permanently after {job['attempts']} attempt(s)",
                {"job_id": job["id"], "error": error})
    return "dead"


def run_one(settings: Settings, conn: psycopg.Connection, job: dict) -> str:
    """Run a claimed job and record the outcome. Returns done/retrying/dead/halted.

    The handler runs OUTSIDE a database transaction on purpose: if it posts something and
    the database then fails, we must not "roll back" a post that really happened. Recording
    the outcome is one all-or-nothing transaction afterwards.
    """
    fn = HANDLERS.get(job["kind"])
    outcome_exc: Exception | None = None
    result: Any = None
    if fn is None:
        outcome_exc = PermanentError(f"no handler for '{job['kind']}'")
    else:
        try:
            result = fn(settings, job["payload"])
        except Exception as e:  # classified below
            outcome_exc = e

    with conn.transaction():
        if outcome_exc is None:
            _finish(conn, job["id"], result)
            log.info(f"Job {job['id']} ({job['kind']}) done")
            return "done"
        if isinstance(outcome_exc, HaltedError):
            # Kill switch: not a failure. Put it back without using up an attempt.
            conn.execute(
                """UPDATE job SET status = 'queued', attempts = attempts - 1,
                                  run_after = now() + %s, locked_at = NULL, locked_by = NULL,
                                  updated_at = now()
                   WHERE id = %s""",
                (HALT_DELAY, job["id"]),
            )
            return "halted"
        # PermanentError: give up now. RetryableError or an unexpected bug: retry with
        # backoff, then give up + alert when attempts run out.
        retryable = not isinstance(outcome_exc, PermanentError)
        return _retry_or_bury(conn, job, outcome_exc, retryable)


def job_counts(conn: psycopg.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, count(*) AS n FROM job GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}
