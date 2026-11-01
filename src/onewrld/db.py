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

    The schema is set with an explicit `SET search_path` after connecting, then VERIFIED.
    (An earlier version passed it as a connection option, which Supabase's pooler silently
    ignores, so tables landed in `public`. See MISTAKES.md M-004.)
    """
    url = url or settings.database_url
    if not url:
        raise PermanentError("DATABASE_URL is not set in .env (see RUNBOOK section 6).")
    if ":6543/" in url:
        # Transaction pooler: it resets SET between transactions, so our schema setting
        # would silently stop applying. Refuse instead of misbehaving.
        raise PermanentError("DATABASE_URL uses port 6543 (transaction pooler). Use the "
                             "Session pooler string (port 5432) instead (RUNBOOK section 6).")
    schema = _check_schema_name(settings.db_schema)
    try:
        conn = psycopg.connect(
            url,
            row_factory=dict_row,
            autocommit=True,
            prepare_threshold=None,
            connect_timeout=10,
            application_name="onewrld-engine",
        )
    except psycopg.OperationalError as e:
        # Network/auth problems. Retryable (the network may come back); message is
        # trimmed so a password can never end up in the logs.
        raise RetryableError(f"Could not connect to database: {str(e).splitlines()[0]}") from None
    try:
        conn.execute(f"SET search_path TO {schema}")
        actual = conn.execute("SELECT current_setting('search_path') AS sp").fetchone()["sp"]
        if actual.strip('"') != schema:
            raise PermanentError(f"Database schema check failed: expected '{schema}', "
                                 f"got '{actual}'. Nothing was changed.")
        yield conn
    finally:
        conn.close()


OUR_TABLES = ("notification", "approval", "alert", "job", "system_flag", "schema_migrations")


def misplaced_tables(settings: Settings, source_schema: str = "public") -> list[str]:
    """Our tables found in the wrong schema (left over from the M-004 bug).
    Only counts them if that schema's schema_migrations proves they are ours."""
    source = _check_schema_name(source_schema)
    with connect(settings) as conn:
        found = {r["table_name"] for r in conn.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema = %s AND table_name = ANY(%s)""",
            (source, list(OUR_TABLES))).fetchall()}
        if "schema_migrations" not in found:
            return []
        ours = conn.execute(
            f"SELECT 1 FROM {source}.schema_migrations WHERE name = '0001_core.sql'").fetchone()
    return [t for t in OUR_TABLES if t in found] if ours else []


def remove_misplaced_tables(settings: Settings, source_schema: str = "public") -> list[str]:
    """Drop ONLY our own table names from the wrong schema, in one all-or-nothing step."""
    source = _check_schema_name(source_schema)
    if source == settings.db_schema:
        raise PermanentError("Refusing to remove tables from the active schema.")
    tables = misplaced_tables(settings, source)
    if tables:
        with connect(settings) as conn, conn.transaction():
            for t in tables:  # names come from OUR_TABLES, never from user input
                conn.execute(f"DROP TABLE IF EXISTS {source}.{t} CASCADE")
        log.warning(f"Removed misplaced tables from '{source}': {tables}")
    return tables


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
