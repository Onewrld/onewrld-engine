"""Diagnose: one command that collects everything needed to debug a problem, WITHOUT secrets.

It writes `diagnose.txt` (never committed) and prints the same thing. It is safe to paste
to Claude: passwords, keys and full connection strings are never included. Only the
database host and port are shown.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from urllib.parse import urlparse

from onewrld import __version__, safety
from onewrld.config import Settings


def _section(out: list[str], title: str) -> None:
    out.append("")
    out.append(f"== {title} ==")


def _safe(fn, out: list[str]) -> None:
    try:
        fn()
    except Exception as e:
        out.append(f"  (could not check: {type(e).__name__}: {str(e).splitlines()[0][:200]})")


def collect(settings: Settings, run_tests: bool = True) -> str:
    out: list[str] = ["ONEWRLD DIAGNOSE REPORT (no secrets included)"]

    _section(out, "system")
    out.append(f"  onewrld {__version__} | python {sys.version.split()[0]} | {platform.platform()}")
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=settings.root,
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "?"
    out.append(f"  code version (git commit): {commit or '?'}")

    _section(out, "settings")
    out.append(f"  MODE={settings.mode}  DB_SCHEMA={settings.db_schema}  "
               f"email_configured={settings.email_configured}")
    if settings.database_url:
        u = urlparse(settings.database_url)
        kind = ("session pooler" if "pooler" in (u.hostname or "") and u.port == 5432 else
                "transaction pooler" if u.port == 6543 else "direct/other")
        out.append(f"  database host={u.hostname} port={u.port} ({kind})")
    else:
        out.append("  database: DATABASE_URL not set")

    _section(out, "kill switch")
    kill_file = settings.state_dir / safety.KILL_FILE_NAME
    out.append(f"  file state/KILL: {'PRESENT: ' + kill_file.read_text().strip() if kill_file.exists() else 'absent'}")
    if settings.database_url:
        def db_flag():
            halted, reason = safety._db_flag(settings)
            out.append(f"  database flag: {'ON: ' + reason if halted else 'off'}")
        _safe(db_flag, out)

    if settings.database_url:
        _section(out, "database")

        def db_report():
            from onewrld import db

            with db.connect(settings) as conn:
                sp = conn.execute("SELECT current_setting('search_path') AS sp").fetchone()["sp"]
                out.append(f"  connected OK, search_path={sp}")
                rows = conn.execute(
                    """SELECT table_schema, string_agg(table_name, ',' ORDER BY table_name) AS t
                       FROM information_schema.tables
                       WHERE table_name = ANY(%s) GROUP BY table_schema ORDER BY 1""",
                    (list(db.OUR_TABLES),)).fetchall()
                for r in rows:
                    out.append(f"  our tables in schema '{r['table_schema']}': {r['t']}")
                if not rows:
                    out.append("  our tables: none found anywhere")
                leftovers = conn.execute(
                    "SELECT count(*) AS n FROM pg_namespace WHERE nspname LIKE 'test\\_%'"
                ).fetchone()["n"]
                out.append(f"  leftover test schemas: {leftovers}")
                if conn.execute("SELECT to_regclass('schema_migrations') IS NOT NULL AS ok"
                                ).fetchone()["ok"]:
                    names = [r["name"] for r in conn.execute(
                        "SELECT name FROM schema_migrations ORDER BY name")]
                    out.append(f"  migrations applied in '{settings.db_schema}': {names}")
                if conn.execute("SELECT to_regclass('job') IS NOT NULL AS ok").fetchone()["ok"]:
                    for r in conn.execute(
                            """SELECT id, kind, status, attempts, left(coalesce(last_error,''),160) AS e
                               FROM job ORDER BY id DESC LIMIT 5"""):
                        out.append(f"  job #{r['id']} {r['kind']} {r['status']} "
                                   f"attempts={r['attempts']} {r['e']}")
                if conn.execute("SELECT to_regclass('alert') IS NOT NULL AS ok").fetchone()["ok"]:
                    for r in conn.execute(
                            """SELECT id, severity, source, left(message,160) AS m FROM alert
                               ORDER BY id DESC LIMIT 5"""):
                        out.append(f"  alert #{r['id']} [{r['severity']}] {r['source']}: {r['m']}")
        _safe(db_report, out)

    _section(out, "recent warnings/errors in the log")
    log_file = settings.log_dir / "onewrld.jsonl"
    if log_file.exists():
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        picked = []
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("level") in ("WARNING", "ERROR", "CRITICAL"):
                picked.append(f"  {e.get('ts')} {e.get('level')} {e.get('module')}: "
                              f"{str(e.get('msg'))[:200]}")
            if len(picked) >= 15:
                break
        out.extend(reversed(picked) if picked else ["  none"])
    else:
        out.append("  no log file yet")

    if run_tests:
        _section(out, "tests (failures only)")
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rfE", "--tb=line",
                               "-p", "no:cacheprovider"],
                              capture_output=True, text=True, cwd=settings.root, timeout=600)
        tail = [l for l in proc.stdout.splitlines()
                if l.startswith(("FAILED", "ERROR", "E ")) or " passed" in l or " failed" in l
                or l.strip().startswith(("C:\\", "/")) and ":" in l]
        out.extend(f"  {l[:300]}" for l in tail[-40:]) if tail else out.append("  (no output)")

    report = "\n".join(out)
    (settings.root / "diagnose.txt").write_text(report + "\n", encoding="utf-8")
    return report
