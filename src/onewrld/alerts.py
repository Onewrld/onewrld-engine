"""Alerts: record anything the owner must know about.

Every alert is saved to the `alert` table and written to the log. Emailing alerts is added
in Module 1.3; until then `python -m onewrld alerts` shows open ones.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from onewrld.logging_setup import get_logger

log = get_logger(__name__)

SEVERITIES = ("info", "warn", "critical")


def raise_alert(
    conn: psycopg.Connection,
    severity: str,
    source: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> int:
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")
    row = conn.execute(
        """INSERT INTO alert (severity, source, message, details)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (severity, source, message, Jsonb(details or {})),
    ).fetchone()
    level = {"info": 20, "warn": 30, "critical": 50}[severity]
    log.log(level, f"ALERT [{severity}] {source}: {message}",
            extra={"fields": {"event": "alert", "alert_id": row["id"]}})
    return row["id"]


def open_alerts(conn: psycopg.Connection, limit: int = 50) -> list[dict]:
    return conn.execute(
        """SELECT id, severity, source, message, created_at FROM alert
           WHERE acknowledged_at IS NULL ORDER BY created_at DESC LIMIT %s""",
        (limit,),
    ).fetchall()


def acknowledge(conn: psycopg.Connection, alert_id: int) -> bool:
    cur = conn.execute(
        "UPDATE alert SET acknowledged_at = now() WHERE id = %s AND acknowledged_at IS NULL",
        (alert_id,),
    )
    return cur.rowcount == 1
