"""Safety: the kill switch and dry-run gate. Every outward action must pass through here.

Kill switch = two flags that must BOTH be off for anything to go out:
  1. a file, `state/KILL`, which works even when the internet or database is down;
  2. a database row (system_flag 'kill_switch'), so every worker and the future dashboard
     see the same stop signal.
If the database is configured but can't be reached, the system treats itself as halted
("fail closed"): when unsure, it stops rather than posts.

Dry-run gate = `outward_action()`. In dry_run mode it logs what WOULD happen and returns
without doing it. In staging/live it runs the real action, but only if not halted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from onewrld.config import Settings
from onewrld.errors import HaltedError, OnewrldError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)
T = TypeVar("T")

KILL_FILE_NAME = "KILL"
DB_FLAG_KEY = "kill_switch"


def _kill_file(settings: Settings):
    return settings.state_dir / KILL_FILE_NAME


def _db_flag(settings: Settings) -> tuple[bool, str]:
    """Returns (halted, reason) from the database. Fails closed on any problem."""
    from onewrld import db  # imported here so safety works without a database

    try:
        with db.connect(settings) as conn:
            row = conn.execute(
                "SELECT value, reason FROM system_flag WHERE key = %s", (DB_FLAG_KEY,)
            ).fetchone()
    except Exception as e:
        if type(e).__name__ == "UndefinedTable":
            return True, "database tables not created yet: run `python -m onewrld migrate`"
        return True, f"could not read the database kill-switch flag, failing safe ({type(e).__name__})"
    if row and row["value"] == "on":
        return True, row["reason"]
    return False, ""


def halt_status(settings: Settings) -> tuple[bool, str | None]:
    """(is_halted, reason). The file is checked first because it needs nothing else to work."""
    f = _kill_file(settings)
    if f.exists():
        return True, f.read_text(encoding="utf-8").strip()
    if settings.database_url:
        halted, reason = _db_flag(settings)
        if halted:
            return True, reason
    return False, None


def is_halted(settings: Settings) -> bool:
    return halt_status(settings)[0]


def halt_reason(settings: Settings) -> str | None:
    return halt_status(settings)[1]


def _set_db_flag(settings: Settings, value: str, reason: str) -> None:
    from onewrld import db

    with db.connect(settings) as conn:
        conn.execute(
            """INSERT INTO system_flag (key, value, reason, updated_at)
               VALUES (%s, %s, %s, now())
               ON CONFLICT (key) DO UPDATE
               SET value = EXCLUDED.value, reason = EXCLUDED.reason, updated_at = now()""",
            (DB_FLAG_KEY, value, reason),
        )


def halt(settings: Settings, reason: str) -> None:
    """Turn the kill switch ON. The file is written first, so the stop takes effect even if
    the database step fails."""
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _kill_file(settings).write_text(f"{stamp} | {reason}\n", encoding="utf-8")
    log.warning("KILL SWITCH ON", extra={"fields": {"event": "halt", "reason": reason}})
    if settings.database_url:
        try:
            _set_db_flag(settings, "on", f"{stamp} | {reason}")
        except Exception as e:
            log.warning(f"Kill switch file is ON, but the database flag could not be set: {e}")


def resume(settings: Settings, reason: str) -> None:
    """Turn the kill switch OFF. Requires a reason. Both flags must clear, or it stays halted."""
    if not reason.strip():
        raise ValueError("A reason is required to resume.")
    if settings.database_url:
        try:
            _set_db_flag(settings, "off", reason)
        except Exception as e:
            raise OnewrldError(
                "Could not clear the database kill switch, so the system stays STOPPED. "
                f"Check your internet/database, then try again. ({type(e).__name__})"
            ) from None
    if _kill_file(settings).exists():
        _kill_file(settings).unlink()
    log.warning("KILL SWITCH OFF", extra={"fields": {"event": "resume", "reason": reason}})


def outward_action(
    settings: Settings,
    name: str,
    action: Callable[[], T],
    details: dict[str, Any] | None = None,
) -> T | None:
    """Run an action that touches the outside world (post, spend, email, API write).

    Order of checks matters: kill switch first (always wins), then dry-run.
    Returns the action's result, or None if it was only simulated.
    """
    details = details or {}
    halted, reason = halt_status(settings)
    if halted:
        log.error(
            f"Refused '{name}': kill switch is on",
            extra={"fields": {"event": "refused", "action": name, **details}},
        )
        raise HaltedError(f"'{name}' refused: kill switch is on ({reason})")

    if settings.mode == "dry_run":
        log.info(
            f"[DRY RUN] would run '{name}'",
            extra={"fields": {"event": "dry_run", "action": name, **details}},
        )
        return None

    log.info(f"Running '{name}'", extra={"fields": {"event": "action", "action": name, **details}})
    return action()
