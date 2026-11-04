"""Health check: one command that tells you, in plain words, whether the system is OK.

Each check returns PASS, WARN (works but needs attention), or FAIL (must fix).
New modules add their own checks here as they are built.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass

from onewrld import safety
from onewrld.config import Settings

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
MIN_FREE_GB = 10  # video work needs room; below this we warn


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def check_python() -> CheckResult:
    ok = sys.version_info >= (3, 11)
    return CheckResult("python", PASS if ok else FAIL, sys.version.split()[0])


def check_mode(settings: Settings) -> CheckResult:
    if settings.mode == "live":
        return CheckResult("mode", WARN, "LIVE: real posting/spending is allowed")
    return CheckResult("mode", PASS, settings.mode)


def check_kill_switch(settings: Settings) -> CheckResult:
    if safety.is_halted(settings):
        return CheckResult("kill_switch", WARN, f"ON: {safety.halt_reason(settings)}")
    return CheckResult("kill_switch", PASS, "off")


def check_alert_email(settings: Settings) -> CheckResult:
    if "@" in settings.alert_email:
        return CheckResult("alert_email", PASS, settings.alert_email)
    return CheckResult("alert_email", WARN, "not set in .env; errors won't reach you")


def check_email(settings: Settings) -> CheckResult:
    if settings.email_configured:
        return CheckResult("email", PASS, f"sends from {settings.smtp_user}")
    return CheckResult("email", WARN, "not set up; alerts won't be emailed (RUNBOOK section 9)")


def check_speech() -> CheckResult:
    from onewrld import speech
    if speech.speech_available():
        return CheckResult("speech", PASS, "speech model installed")
    if sys.version_info >= (3, 15):
        return CheckResult("speech", WARN, f"not installable on Python {sys.version.split()[0]} yet; "
                                            "see RUNBOOK section 14")
    return CheckResult("speech", WARN, 'optional, not installed: pip install -e ".[speech]"')


def check_ffmpeg() -> CheckResult:
    path = shutil.which("ffmpeg")
    if path:
        return CheckResult("ffmpeg", PASS, path)
    return CheckResult("ffmpeg", WARN, "not installed (needed from Phase 3)")


def check_disk(settings: Settings) -> CheckResult:
    free_gb = shutil.disk_usage(settings.root).free / 1e9
    status = PASS if free_gb >= MIN_FREE_GB else WARN
    return CheckResult("disk", status, f"{free_gb:.0f} GB free")


def check_database(settings: Settings) -> CheckResult:
    if not settings.database_url:
        return CheckResult("database", WARN, "not configured yet (RUNBOOK section 6)")
    from onewrld import db

    try:
        with db.connect(settings) as conn:
            conn.execute("SELECT 1")
            pending = db.pending_migrations(settings, conn)
    except Exception as e:
        return CheckResult("database", FAIL, f"cannot connect: {e}")
    try:
        stray = db.misplaced_tables(settings, "public")
    except Exception:
        stray = []
    if stray:
        return CheckResult("database", FAIL, "old tables found in 'public' (bug M-004): "
                           "run `python -m onewrld repair-schema --yes`")
    if pending:
        names = ", ".join(p.name for p in pending)
        return CheckResult("database", WARN, f"connected; run `migrate` to apply: {names}")
    return CheckResult("database", PASS, f"connected, schema '{settings.db_schema}' up to date")


def run_all(settings: Settings) -> list[CheckResult]:
    return [
        check_python(),
        check_mode(settings),
        check_kill_switch(settings),
        check_alert_email(settings),
        check_email(settings),
        check_ffmpeg(),
        check_speech(),
        check_disk(settings),
        check_database(settings),
    ]
