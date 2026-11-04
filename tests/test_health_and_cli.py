from onewrld import health, safety
from onewrld.cli import main


def test_health_passes_on_fresh_setup(make_settings):
    results = health.run_all(make_settings(ALERT_EMAIL="a@b.com"))
    assert not [r for r in results if r.status == health.FAIL]


def test_health_warns_when_halted(make_settings):
    s = make_settings()
    safety.halt(s, "x")
    ks = [r for r in health.run_all(s) if r.name == "kill_switch"][0]
    assert ks.status == health.WARN


def test_health_warns_when_live(make_settings):
    m = [r for r in health.run_all(make_settings(MODE="live")) if r.name == "mode"][0]
    assert m.status == health.WARN


def test_cli_kill_blocks_demo_action(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ONEWRLD_ROOT", str(tmp_path))
    monkeypatch.setenv("MODE", "live")
    assert main(["kill", "test stop"]) == 0
    assert main(["demo-action"]) == 2  # blocked
    assert "Blocked" in capsys.readouterr().out
    assert main(["resume", "test over"]) == 0
    assert main(["demo-action"]) == 0


def test_venv_check_reports_both_states(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "prefix", "/x/.venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    assert health.check_venv().status == health.PASS
    monkeypatch.setattr(sys, "prefix", "/usr")
    assert health.check_venv().status == health.WARN
