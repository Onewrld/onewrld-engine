import pytest

from onewrld import safety
from onewrld.errors import HaltedError


def _counter():
    calls = []
    return calls, lambda: calls.append(1) or "done"


def test_dry_run_never_executes(make_settings):
    s = make_settings(MODE="dry_run")
    calls, action = _counter()
    assert safety.outward_action(s, "post", action) is None
    assert calls == []


def test_live_executes_when_not_halted(make_settings):
    s = make_settings(MODE="live")
    calls, action = _counter()
    assert safety.outward_action(s, "post", action) == "done"
    assert calls == [1]


@pytest.mark.parametrize("mode", ["dry_run", "staging", "live"])
def test_kill_switch_blocks_every_mode(make_settings, mode):
    s = make_settings(MODE=mode)
    safety.halt(s, "test")
    calls, action = _counter()
    with pytest.raises(HaltedError):
        safety.outward_action(s, "post", action)
    assert calls == []


def test_resume_requires_reason(make_settings):
    s = make_settings()
    safety.halt(s, "test")
    with pytest.raises(ValueError):
        safety.resume(s, "  ")
    assert safety.is_halted(s)


def test_halt_then_resume(make_settings):
    s = make_settings(MODE="live")
    safety.halt(s, "spend spike")
    assert "spend spike" in safety.halt_reason(s)
    safety.resume(s, "checked, false alarm")
    assert not safety.is_halted(s)
    calls, action = _counter()
    safety.outward_action(s, "post", action)
    assert calls == [1]
