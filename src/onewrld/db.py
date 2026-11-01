"""Database: connecting to Postgres (Supabase) and applying migrations.

A migration is a numbered SQL file in `db/migrations/` that changes the database structure
(for example, "create the job table"). Each one runs exactly once, in number order. The
`schema_migrations` table remembers which ones have already run, so `migrate` is safe to
run any number of times.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from onewrld.config import PROJECT_ROOT, Settings
from onewrld.errors import PermanentError, RetryableError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)

SCHEMA_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")


def migrations_dir(settings: Settings) -> Path:
    # Migrations ship with the code, so they live next to it (not in the data folder).
    return PROJECT_ROOT / "db" / "migrations"


def _check_schema_name(name: str) -> str:
    # The schema name goes into SQL text, so only allow safe characters.
    if not SCHEMA_NAME_RE.match(name):
        raise PermanentError(f"Invalid DB_SCHEMA '{name}'. Use lowercase letters, digits, _.")
    return name


@contextmanager
def connect(settings: Settings, url: str | None = None) -> Iterator[psycopg.Connection]:
    """Open a connection, pointed at our schema. Closes automatically.

    autocommit=True: each statement saves immediately unless it is inside an explicit
    `with conn.transaction():` block, which saves all-or-nothing.
    prepare_threshold=None turns off "prepared statements", which Supabase's connection
    pooler doesn't support well. connect_timeout stops us waiting forever on a bad network.
    """
    url = url or settings.database_url
    if not url:
        raise PermanentError("DATABASE_URL is not set in .env (see RUNBOOK section 6).")
    schema = _check_schema_name(settings.db_schema)
    try:
        conn = psycopg.connect(
            url,
            row_factory=dict_row,
            autocommit=True,
            prepare_threshold=None,
            connect_timeout=10,
            options=f"-c search_path={schema}",
            application_name="onewrld-engine",
        )
    except psycopg.OperationalError as e:
        # Network/auth problems. Retryable (the network may come back); message is
        # trimmed so a password can never end up in the logs.
        raise RetryableError(f"Could not connect to database: {str(e).splitlines()[0]}") from None
    try:
        yield conn
    finally:
        conn.close()


def _migration_files(settings: Settings) -> list[Path]:
    return sorted(migrations_dir(settings).glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _ensure_bookkeeping(conn: psycopg.Connection, schema: str) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               name text PRIMARY KEY,
               applied_at timestamptz NOT NULL DEFAULT now())"""
    )
    conn.execute("ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY")


def applied_migrations(conn: psycopg.Connection) -> set[str]:
    exists = conn.execute(
        "SELECT to_regclass('schema_migrations') IS NOT NULL AS ok"
    ).fetchone()["ok"]
    if not exists:
        return set()
    return {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}


def pending_migrations(settings: Settings, conn: psycopg.Connection) -> list[Path]:
    done = applied_migrations(conn)
    return [f for f in _migration_files(settings) if f.name not in done]


def migrate(settings: Settings, url: str | None = None) -> list[str]:
    """Apply every migration that hasn't run yet. Each runs in its own transaction:
    if one fails, nothing from it is kept and later ones don't run."""
    schema = _check_schema_name(settings.db_schema)
    applied: list[str] = []
    with connect(settings, url) as conn:
        with conn.transaction():
            _ensure_bookkeeping(conn, schema)
        for f in pending_migrations(settings, conn):
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
            log.info(f"Applied migration {f.name}", extra={"fields": {"event": "migration"}})
            applied.append(f.name)
    return applied
