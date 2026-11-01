"""Logging: every module writes to the same two places.

1. Your terminal, in short readable lines.
2. `logs/onewrld.jsonl`, one JSON object per line, so the system (and later the
   dashboard) can search and count errors. "Structured logging" = logs as data, not prose.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_CONFIGURED = False


class JsonLineFormatter(logging.Formatter):
    """Turns a log record into one line of JSON."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
        }
        # Extra fields passed as logger.info("...", extra={"fields": {...}})
        fields = getattr(record, "fields", None)
        if fields:
            entry.update(fields)
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    """Configure logging once per process. Safe to call more than once."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("onewrld")
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(console)

    file_handler = logging.FileHandler(log_dir / "onewrld.jsonl", encoding="utf-8")
    file_handler.setFormatter(JsonLineFormatter())
    root.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Use in every module: `log = get_logger(__name__)`."""
    return logging.getLogger(name if name.startswith("onewrld") else f"onewrld.{name}")
