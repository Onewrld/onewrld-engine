"""Safety: the kill switch and dry-run gate. Every outward action must pass through here.

Kill switch = a flag file (`state/KILL`). While it exists, every post, spend, and send is
refused. It is a file (not only a database row) so it still works when the database or
internet is down.

Dry-run gate = `outward_action()`. In dry_run mode it logs what WOULD happen and returns
without doing it. In staging/live it runs the real action, but only if the kill switch is off.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from onewrld.config import Settings
from onewrld.errors import HaltedError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)
T = TypeVar("T")

KILL_FILE_NAME = "KILL"


def _kill_file(settings: Settings):
    return settings.state_dir / KILL_FILE_NAME


def is_halted(settings: Settings) -> bool:
    return _kill_file(settings).exists()


def halt(settings: Settings, reason: str) -> None:
    """Turn the kill switch ON. Records who/why/when inside the flag file."""
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _kill_file(settings).write_text(f"{stamp} | {reason}\n", encoding="utf-8")
    log.warning("KILL SWITCH ON", extra={"fields": {"event": "halt", "reason": reason}})


def resume(settings: Settings, reason: str) -> None:
    """Turn the kill switch OFF. Requires a reason so it is never flipped by accident."""
    if not reason.strip():
        raise ValueError("A reason is required to resume.")
    if _kill_file(settings).exists():
        _kill_file(settings).unlink()
    log.warning("KILL SWITCH OFF", extra={"fields": {"event": "resume", "reason": reason}})


def halt_reason(settings: Settings) -> str | None:
    f = _kill_file(settings)
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


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
    if is_halted(settings):
        log.error(
            f"Refused '{name}': kill switch is on",
            extra={"fields": {"event": "refused", "action": name, **details}},
        )
        raise HaltedError(f"'{name}' refused: kill switch is on ({halt_reason(settings)})")

    if settings.mode == "dry_run":
        log.info(
            f"[DRY RUN] would run '{name}'",
            extra={"fields": {"event": "dry_run", "action": name, **details}},
        )
        return None

    log.info(f"Running '{name}'", extra={"fields": {"event": "action", "action": name, **details}})
    return action()
