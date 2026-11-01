"""Shared test setup: every test gets its own empty project folder, so tests never touch
your real `.env`, kill switch, or logs."""

import pytest

from onewrld.config import load_settings


@pytest.fixture
def make_settings(tmp_path, monkeypatch):
    def _make(**env):
        for key in ("MODE", "ALERT_EMAIL", "DATABASE_URL"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return load_settings(root=tmp_path)

    return _make
