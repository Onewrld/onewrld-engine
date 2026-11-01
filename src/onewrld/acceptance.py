"""Phase 1 acceptance check: one command that proves the foundation works on YOUR setup.

It runs real drills against your real database, but only with harmless demo jobs:
  1. health has no failures and the database is up to date
  2. every automated test passes
  3. kill switch drill: turn on -> a demo post is blocked -> turn off
  4. job drill: queue a demo post -> run it -> it finishes (dry run, nothing real posted)
  5. email drill: a test email reaches ALERT_EMAIL
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from typing import Callable

from onewrld import db, health, jobs, notify, safety
from onewrld.config import Settings
from onewrld.errors import HaltedError

import onewrld.handlers  # noqa: F401  (registers demo handlers)


def _health(settings: Settings) -> tuple[bool, str]:
    results = health.run_all(settings)
    bad = [r for r in results if r.status == health.FAIL]
    dbr = next(r for r in results if r.name == "database")
    if bad:
        return False, "; ".join(f"{r.name}: {r.detail}" for r in bad)
    if dbr.status != health.PASS:
        return False, f"database: {dbr.detail}"
    return True, "no failures; database up to date"


def _tests(settings: Settings) -> tuple[bool, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True,
                          text=True, cwd=settings.root)
    last = (proc.stdout.strip().splitlines() or ["no output"])[-1]
    return proc.returncode == 0, last


def _kill_drill(settings: Settings) -> tuple[bool, str]:
    if safety.is_halted(settings):
        return False, "kill switch is already ON; run `resume` first, then re-run this check"
    safety.halt(settings, "phase1-check drill")
    try:
        safety.outward_action(settings, "drill_post", lambda: "should never run")
        blocked = False
    except HaltedError:
        blocked = True
    finally:
        safety.resume(settings, "phase1-check drill finished")
    if not blocked:
        return False, "a demo action was NOT blocked while the kill switch was on"
    return not safety.is_halted(settings), "blocked while ON, clear after resume"


def _job_drill(settings: Settings) -> tuple[bool, str]:
    with db.connect(settings) as conn:
        job_id, _ = jobs.enqueue(conn, "demo.post", {"text": "phase1 drill"},
                                 idempotency_key=f"phase1-drill:{uuid.uuid4()}")
        with conn.transaction():
            # Claim this exact job (not whatever else might be queued).
            job = conn.execute(
                """UPDATE job SET status='running', locked_at=now(), locked_by='phase1-check',
                                  attempts=attempts+1, updated_at=now()
                   WHERE id=%s AND status='queued' RETURNING *""", (job_id,)).fetchone()
        outcome = jobs.run_one(settings, conn, job)
        row = conn.execute("SELECT status, result FROM job WHERE id=%s", (job_id,)).fetchone()
    ok = outcome == "done" and row["status"] == "done"
    note = "dry run, nothing posted" if (row["result"] or {}).get("dry_run") else str(row["result"])
    return ok, f"job #{job_id} {row['status']} ({note})"


def _email_drill(settings: Settings) -> tuple[bool, str]:
    if not settings.email_configured:
        return False, "email not configured (RUNBOOK section 9)"
    try:
        with db.connect(settings) as conn:
            notify.send_test_email(settings, conn)
    except Exception as e:
        return False, str(e)
    return True, f"sent to {settings.alert_email}; check your inbox (and spam)"


CHECKS: list[tuple[str, Callable[[Settings], tuple[bool, str]]]] = [
    ("health", _health),
    ("tests", _tests),
    ("kill switch drill", _kill_drill),
    ("job drill", _job_drill),
    ("email drill", _email_drill),
]


def run(settings: Settings) -> bool:
    all_ok = True
    for name, fn in CHECKS:
        try:
            ok, detail = fn(settings)
        except Exception as e:  # a crashing check is a failed check, never a silent one
            ok, detail = False, f"{type(e).__name__}: {e}"
        all_ok &= ok
        print(f"{'[PASS]' if ok else '[FAIL]'} {name:<18} {detail}")
    print("\nPhase 1:", "ACCEPTED" if all_ok else "NOT YET; fix the [FAIL] lines above")
    return all_ok
