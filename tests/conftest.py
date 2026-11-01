"""Shared test setup.

- Every test gets its own empty project folder, so tests never touch your real `.env`,
  kill switch, or logs.
- Database tests run inside a brand-new throwaway schema (named test_xxxxxxxx) that is
  deleted afterwards, so they can never touch the real `engine` tables. They use
  TEST_DATABASE_URL if set, otherwise the DATABASE_URL in your `.env`. With neither,
  they are skipped (and say so).
"""

import os
import uuid

import psycopg
import pytest
from dotenv import dotenv_values

from onewrld.config import PROJECT_ROOT, load_settings

ENV_KEYS = ("MODE", "ALERT_EMAIL", "DATABASE_URL", "DB_SCHEMA", "ONEWRLD_ROOT")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def make_settings(tmp_path, monkeypatch):
    def _make(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return load_settings(root=tmp_path)

    return _make


def _test_db_url() -> str | None:
    return (os.environ.get("TEST_DATABASE_URL")
            or dotenv_values(PROJECT_ROOT / ".env").get("DATABASE_URL")
            or None)


@pytest.fixture
def db_settings(make_settings):
    """Settings pointed at a fresh, fully migrated throwaway schema."""
    url = _test_db_url()
    if not url:
        pytest.skip("no database configured (set DATABASE_URL in .env to run DB tests)")
    from onewrld import db

    schema = f"test_{uuid.uuid4().hex[:8]}"
    settings = make_settings(DATABASE_URL=url, DB_SCHEMA=schema)
    db.migrate(settings)
    try:
        yield settings
    finally:
        with psycopg.connect(url, autocommit=True, prepare_threshold=None) as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture
def conn(db_settings):
    from onewrld import db

    with db.connect(db_settings) as c:
        yield c
