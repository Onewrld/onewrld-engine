"""Database, job queue, worker and database kill switch."""

import psycopg
import pytest

from onewrld import alerts, db, jobs, safety
from onewrld.config import load_settings
from onewrld.worker import run_worker


def _force_due(conn, job_id):
    """Skip the backoff wait so the test doesn't have to sleep."""
    conn.execute("UPDATE job SET run_after = now() WHERE id = %s", (job_id,))


def _job(conn, job_id):
    return conn.execute("SELECT * FROM job WHERE id = %s", (job_id,)).fetchone()


# --- migrations -------------------------------------------------------------

def test_migrate_is_safe_to_rerun(db_settings):
    assert db.migrate(db_settings) == []  # already applied by the fixture


def test_tables_have_row_level_security(conn):
    rows = conn.execute(
        """SELECT relname, relrowsecurity FROM pg_class
           WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r'"""
    ).fetchall()
    assert rows and all(r["relrowsecurity"] for r in rows)


def test_invalid_schema_name_rejected(make_settings):
    from onewrld.errors import PermanentError

    s = make_settings(DATABASE_URL="postgresql://x@localhost/x", DB_SCHEMA="bad; drop")
    with pytest.raises(PermanentError):
        with db.connect(s):
            pass


# --- queue ------------------------------------------------------------------

def test_enqueue_is_idempotent(conn):
    a, created_a = jobs.enqueue(conn, "demo.post", {}, "same-key")
    b, created_b = jobs.enqueue(conn, "demo.post", {}, "same-key")
    assert a == b and created_a and not created_b
    assert conn.execute("SELECT count(*) AS n FROM job").fetchone()["n"] == 1


def test_two_workers_never_claim_the_same_job(db_settings):
    with db.connect(db_settings) as c1, db.connect(db_settings) as c2:
        jobs.enqueue(c1, "demo.post", {}, "only-one")
        with c1.transaction():
            first = jobs.claim(c1, "w1")
            # c1 still holds the row lock; c2 must skip it
            with c2.transaction():
                second = jobs.claim(c2, "w2")
        assert first is not None and second is None


def test_dry_run_job_completes_without_posting(db_settings, conn):
    job_id, _ = jobs.enqueue(conn, "demo.post", {"text": "hi"}, "k1")
    stats = run_worker(db_settings, max_jobs=5, max_seconds=30)
    assert stats["done"] == 1
    row = _job(conn, job_id)
    assert row["status"] == "done" and row["result"]["dry_run"] is True


def test_retryable_failure_backs_off_then_dies_with_alert(db_settings, conn):
    job_id, _ = jobs.enqueue(conn, "demo.fail", {}, "k2", max_attempts=2)
    run_worker(db_settings, max_jobs=1, max_seconds=30)
    row = _job(conn, job_id)
    assert row["status"] == "queued" and row["attempts"] == 1
    assert row["run_after"] > row["updated_at"]  # waiting for backoff
    _force_due(conn, job_id)
    run_worker(db_settings, max_jobs=1, max_seconds=30)
    row = _job(conn, job_id)
    assert row["status"] == "dead" and row["attempts"] == 2
    assert len(alerts.open_alerts(conn)) == 1


def test_permanent_failure_dies_immediately(db_settings, conn):
    job_id, _ = jobs.enqueue(conn, "demo.fail", {"permanent": True}, "k3")
    run_worker(db_settings, max_jobs=1, max_seconds=30)
    assert _job(conn, job_id)["status"] == "dead"
    assert _job(conn, job_id)["attempts"] == 1


def test_unknown_job_kind_goes_dead(db_settings, conn):
    job_id, _ = jobs.enqueue(conn, "no.such.kind", {}, "k4")
    run_worker(db_settings, max_jobs=1, max_seconds=30)
    assert _job(conn, job_id)["status"] == "dead"


def test_backoff_grows_and_is_capped():
    assert 24 <= jobs.backoff_seconds(1) <= 36
    assert 48 <= jobs.backoff_seconds(2) <= 72
    assert jobs.backoff_seconds(30) <= jobs.MAX_BACKOFF_SECONDS * 1.2


def test_worker_is_bounded_by_max_jobs(db_settings, conn):
    for i in range(5):
        jobs.enqueue(conn, "demo.post", {}, f"bulk-{i}")
    stats = run_worker(db_settings, max_jobs=2, max_seconds=30)
    assert stats.total() == 2
    assert jobs.job_counts(conn)["queued"] == 3


def test_stale_running_job_is_requeued(conn):
    job_id, _ = jobs.enqueue(conn, "demo.post", {}, "stale")
    conn.execute(
        "UPDATE job SET status='running', locked_at = now() - interval '2 hours' WHERE id=%s",
        (job_id,),
    )
    assert jobs.requeue_stale(conn) == 1
    assert _job(conn, job_id)["status"] == "queued"


def test_alert_acknowledge(conn):
    aid = alerts.raise_alert(conn, "info", "test", "hello")
    assert alerts.acknowledge(conn, aid)
    assert not alerts.acknowledge(conn, aid)  # already acknowledged
    assert alerts.open_alerts(conn) == []


# --- kill switch with database ----------------------------------------------

def test_db_kill_switch_holds_even_if_file_deleted(db_settings):
    safety.halt(db_settings, "db test")
    (db_settings.state_dir / safety.KILL_FILE_NAME).unlink()  # simulate file lost
    assert safety.is_halted(db_settings)  # database flag still stops everything
    safety.resume(db_settings, "done")
    assert not safety.is_halted(db_settings)


def test_worker_stops_and_job_keeps_its_attempts_when_halted(db_settings, conn):
    job_id, _ = jobs.enqueue(conn, "demo.post", {}, "halt-me")
    safety.halt(db_settings, "stop")
    stats = run_worker(db_settings, max_jobs=5, max_seconds=30)
    assert stats["stopped_by_kill_switch"] == 1
    row = _job(conn, job_id)
    assert row["status"] == "queued" and row["attempts"] == 0
    safety.resume(db_settings, "go")


def test_halted_inside_handler_does_not_use_an_attempt(db_settings, conn):
    job_id, _ = jobs.enqueue(conn, "demo.post", {}, "mid-halt")
    with conn.transaction():
        job = jobs.claim(conn, "w")
    safety.halt(db_settings, "mid-run")
    assert jobs.run_one(db_settings, conn, job) == "halted"
    row = _job(conn, job_id)
    assert row["status"] == "queued" and row["attempts"] == 0
    safety.resume(db_settings, "go")


def test_unreachable_database_fails_closed(make_settings):
    s = make_settings(DATABASE_URL="postgresql://nobody:x@127.0.0.1:1/none")
    halted, reason = safety.halt_status(s)
    assert halted and "failing safe" in reason
