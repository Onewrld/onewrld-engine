"""Affiliate Portal website: no secrets shipped, only local scripts, security headers set,
buttons call functions that exist in the database, and the browser smoke test."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from onewrld.config import PROJECT_ROOT

SITE = PROJECT_ROOT / "portal"


def _site_text():
    return {p: p.read_text(encoding="utf-8", errors="replace")
            for p in SITE.rglob("*") if p.suffix in {".html", ".js", ".css"} and "vendor" not in p.parts}


def test_no_secret_keys_in_the_website():
    for path, text in _site_text().items():
        assert "service_role" not in text.lower() or "never" in text.lower(), path
        # JWT-looking strings (how Supabase keys look) must never be committed in the site
        assert not re.search(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.", text), path
        assert "sb_secret_" not in text or "never" in text.lower(), path       # new-style secret key


def test_scripts_are_local_files_that_exist():
    html = (SITE / "index.html").read_text()
    srcs = re.findall(r'<script src="([^"]+)"', html)
    assert srcs and all(not s.startswith(("http:", "https:", "//")) for s in srcs)
    assert all((SITE / s).exists() for s in srcs)


def test_netlify_publishes_portal_with_strict_headers():
    toml = (PROJECT_ROOT / "netlify.toml").read_text()
    assert 'publish = "portal"' in toml
    assert "script-src 'self'" in toml and "frame-ancestors 'none'" in toml


def test_buttons_call_database_functions_that_exist():
    js = (SITE / "app.js").read_text()
    sql = "".join(p.read_text() for p in (PROJECT_ROOT / "db" / "portal").glob("*.sql"))
    for fn in set(re.findall(r'\.rpc\("([a-z_]+)"', js)):
        assert f"FUNCTION {{{{schema}}}}.{fn}(" in sql, fn


def _node_playwright():
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _node_playwright(), reason="node + playwright not available")
def test_browser_smoke(tmp_path):
    out = subprocess.run(["node", str(PROJECT_ROOT / "tests" / "portal_smoke.mjs"), str(tmp_path)],
                         capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=240)
    assert "SMOKE TEST PASSED" in out.stdout, out.stdout[-2000:] + out.stderr[-2000:]
