"""Autopilot: the Windows scheduled task for portal sync (fake schtasks, nothing really scheduled)."""

from types import SimpleNamespace

from onewrld import autopilot


def test_on_off_and_state_use_windows_task_scheduler():
    seen = []

    def runner(args, **kw):
        seen.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    ok, msg = autopilot.turn_on(10, runner=runner, platform="win32")
    assert ok and "every 10 minutes" in msg
    cmd = seen[0]
    assert cmd[:3] == ["schtasks", "/create", "/f"] and cmd[cmd.index("/mo") + 1] == "10"
    assert cmd[-1].endswith("-m onewrld portal sync") and cmd[cmd.index("/tn") + 1] == autopilot.TASK
    assert autopilot.state(runner=runner, platform="win32") == "ON"
    assert autopilot.turn_off(runner=runner, platform="win32")[0]


def test_interval_is_bounded_and_errors_are_shown():
    assert autopilot.command(1)[6] == "5" and autopilot.command(999)[6] == "60"
    refuse = lambda a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Access is denied.")
    ok, msg = autopilot.turn_on(10, runner=refuse, platform="win32")
    assert not ok and "Access is denied" in msg
    assert autopilot.state(runner=refuse, platform="win32") == "OFF"
    assert not autopilot.turn_on(10, platform="linux")[0]
