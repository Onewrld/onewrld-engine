import pytest

from onewrld.config import ConfigError, load_settings


def test_default_mode_is_dry_run(make_settings):
    # Safety default: if nobody sets MODE, nothing real can happen.
    assert make_settings().mode == "dry_run"


def test_invalid_mode_is_rejected(make_settings):
    with pytest.raises(ConfigError, match="not valid"):
        make_settings(MODE="yolo")


def test_env_file_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL", raising=False)
    monkeypatch.delenv("MODE", raising=False)
    (tmp_path / ".env").write_text("MODE=staging\nALERT_EMAIL=a@b.com\n")
    s = load_settings(root=tmp_path)
    assert s.mode == "staging"
    assert s.alert_email == "a@b.com"


def test_env_example_never_contains_real_secrets():
    # .env.example is committed; it must only hold placeholders.
    from onewrld.config import PROJECT_ROOT

    text = (PROJECT_ROOT / ".env.example").read_text()
    db_line = [l for l in text.splitlines() if l.startswith("DATABASE_URL=")][0]
    assert db_line == "DATABASE_URL="


def test_gitignore_blocks_env():
    from onewrld.config import PROJECT_ROOT

    lines = (PROJECT_ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in lines
