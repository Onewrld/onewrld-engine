"""Affiliate Portal (database side): set up the portal tables in Supabase, invite affiliates,
make yourself the owner.

The portal's tables live in Supabase's `public` schema (so the website can reach them through
Supabase's API, protected by Row Level Security). The engine's own tables stay private in
`engine`. Setup SQL is in db/portal/; each file runs once, recorded in schema_migrations.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import psycopg

from onewrld.config import PROJECT_ROOT, Settings
from onewrld.errors import PermanentError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)
PORTAL_DIR = PROJECT_ROOT / "db" / "portal"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _files() -> list[Path]:
    return sorted(PORTAL_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def setup(conn: psycopg.Connection, schema: str = "public") -> list[str]:
    """Apply portal SQL files not yet applied to `schema`. Needs Supabase's `auth` schema."""
    if not re.match(r"^[a-z_][a-z0-9_]{0,40}$", schema):
        raise PermanentError(f"invalid schema name {schema!r}")
    has_auth = conn.execute("""SELECT to_regclass('auth.users') IS NOT NULL
                                      AND to_regclass('storage.objects') IS NOT NULL AS ok""").fetchone()["ok"]
    if not has_auth:
        raise PermanentError("This database has no Supabase login system (auth.users). "
                             "Run portal setup against your Supabase project.")
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for f in _files():
        name = f"portal:{schema}:{f.name}"
        if name in done:
            continue
        sql = f.read_text(encoding="utf-8").replace("{{schema}}", schema)
        with conn.transaction():
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (name,))
        applied.append(f.name)
        log.info(f"Portal: applied {f.name} to schema {schema}")
    return applied


def invite(conn: psycopg.Connection, email: str, name: str, code: str | None = None,
           link: str | None = None, schema: str = "public") -> None:
    """Allow this email to log in as an affiliate. Re-inviting updates their details."""
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise PermanentError(f"'{email}' doesn't look like an email address")
    with conn.transaction():
        conn.execute(
            f"""INSERT INTO {schema}.invites (email, display_name, discount_code, ref_link)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (email) DO UPDATE SET display_name = EXCLUDED.display_name,
                    discount_code = EXCLUDED.discount_code, ref_link = EXCLUDED.ref_link""",
            (email, name.strip(), code, link))
        # already logged in once? keep their profile in step with the invite
        conn.execute(
            f"""UPDATE {schema}.profiles SET display_name=%s, discount_code=%s, ref_link=%s
                WHERE email=%s""", (name.strip(), code, link, email))


def create_login(settings: Settings, email: str, opener=urllib.request.urlopen) -> str:
    """Create the person's Supabase login (confirmed email, no password) so the portal's
    "send me a login link" works for them. Returns 'created', 'exists' or 'skipped'
    (no Supabase admin key configured)."""
    if not (settings.supabase_url and settings.supabase_service_key):
        return "skipped"
    key = settings.supabase_service_key
    headers = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_secret_"):
        # Legacy service_role keys are JWTs and go in both headers. New sb_secret_ keys
        # are NOT JWTs: Supabase rejects them as a Bearer token, so apikey header only.
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        f"{settings.supabase_url}/auth/v1/admin/users", method="POST",
        data=json.dumps({"email": email.strip().lower(), "email_confirm": True}).encode(),
        headers=headers)
    try:
        with opener(req, timeout=20):
            return "created"
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 422 or "already" in body.lower():
            return "exists"
        raise PermanentError(f"Supabase refused to create the login ({e.code}): {body[:200]}") from None
    except OSError as e:
        raise PermanentError(f"Couldn't reach Supabase to create the login: {e}") from None


def make_owner(conn: psycopg.Connection, email: str, schema: str = "public") -> bool:
    """Give an existing login the owner role (you). They must have logged in once."""
    cur = conn.execute(f"UPDATE {schema}.profiles SET role='owner' WHERE email=%s",
                       (email.strip().lower(),))
    return cur.rowcount == 1


def set_active(conn: psycopg.Connection, email: str, active: bool, schema: str = "public") -> bool:
    cur = conn.execute(f"UPDATE {schema}.profiles SET active=%s WHERE email=%s",
                       (active, email.strip().lower()))
    return cur.rowcount == 1


def members(conn: psycopg.Connection, schema: str = "public") -> list[dict]:
    return conn.execute(
        f"""SELECT i.email, i.display_name, i.discount_code, p.role, p.active,
                   (p.id IS NOT NULL) AS has_logged_in
            FROM {schema}.invites i LEFT JOIN {schema}.profiles p ON p.email = i.email
            UNION
            SELECT p.email, p.display_name, p.discount_code, p.role, p.active, true
            FROM {schema}.profiles p WHERE NOT EXISTS
                 (SELECT 1 FROM {schema}.invites i WHERE i.email = p.email)
            ORDER BY 1""").fetchall()
