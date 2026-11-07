"""Autopilot: Windows runs `portal sync` every few minutes while the PC is on (D-067).

Uses Windows Task Scheduler (`schtasks`, built into Windows; nothing to install). Runs with
pythonw.exe when it exists, so no black window pops up every 10 minutes. Safe: a run that
starts while another is still editing exits straight away (portal_sync.LOCK_KEY), and each
run is bounded (portal_sync.MAX_UPLOADS / MAX_MINUTES).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TASK = "ONEWRLD portal sync"


def _python() -> str:
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    return str(quiet if quiet.exists() else exe)


def command(every: int) -> list[str]:
    every = max(5, min(60, every))
    return ["schtasks", "/create", "/f", "/sc", "minute", "/mo", str(every), "/tn", TASK,
            "/tr", f'"{_python()}" -m onewrld portal sync']


def _run(args: list[str], runner=subprocess.run):
    return runner(args, capture_output=True, text=True)


def turn_on(every: int = 10, runner=subprocess.run, platform: str = sys.platform) -> tuple[bool, str]:
    cmd = command(every)
    if not platform.startswith("win"):
        return False, "Autopilot uses Windows Task Scheduler. Run this on your Windows PC."
    out = _run(cmd, runner)
    if out.returncode != 0:
        return False, f"Windows refused: {(out.stderr or out.stdout).strip()[:300]}"
    return True, (f"Autopilot ON: your PC edits new uploads every {cmd[6]} minutes while it's on. "
                  "Stop with: python -m onewrld portal autopilot off")


def turn_off(runner=subprocess.run, platform: str = sys.platform) -> tuple[bool, str]:
    if not platform.startswith("win"):
        return False, "Autopilot uses Windows Task Scheduler. Run this on your Windows PC."
    out = _run(["schtasks", "/delete", "/f", "/tn", TASK], runner)
    if out.returncode != 0 and "cannot find" not in (out.stderr or "").lower():
        return False, f"Windows refused: {(out.stderr or out.stdout).strip()[:300]}"
    return True, "Autopilot OFF. Run python -m onewrld portal sync yourself when you want."


def state(runner=subprocess.run, platform: str = sys.platform) -> str:
    if not platform.startswith("win"):
        return "n/a (not Windows)"
    try:
        out = _run(["schtasks", "/query", "/tn", TASK], runner)
    except OSError:
        return "unknown"
    return "ON" if out.returncode == 0 else "OFF"
