"""Command line: the buttons you press. Run `python -m onewrld --help` to see them all.

Commands:
  health                 show whether everything is OK
  status                 show mode + kill switch in one line
  kill  "reason"         STOP all posting and spending immediately
  resume "reason"        turn the kill switch back off
  test                   run every automated test
  demo-action            simulate an outward action (shows dry-run + kill switch working)
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from onewrld import health, safety
from onewrld.config import ConfigError, load_settings
from onewrld.errors import HaltedError
from onewrld.logging_setup import setup_logging

ICONS = {health.PASS: "[ OK ]", health.WARN: "[WARN]", health.FAIL: "[FAIL]"}


def _cmd_health(settings) -> int:
    results = health.run_all(settings)
    for r in results:
        print(f"{ICONS[r.status]} {r.name:<12} {r.detail}")
    failed = [r for r in results if r.status == health.FAIL]
    print("\nOverall:", "FAIL" if failed else "OK")
    return 1 if failed else 0


def _cmd_status(settings) -> int:
    kill = "ON" if safety.is_halted(settings) else "off"
    print(f"mode={settings.mode}  kill_switch={kill}")
    return 0


def _cmd_demo_action(settings) -> int:
    try:
        result = safety.outward_action(
            settings,
            "demo_post",
            lambda: "posted (demo; nothing real happened)",
            details={"platform": "demo"},
        )
    except HaltedError as e:
        print(f"Blocked: {e}")
        return 2
    print("Result:", result if result is not None else "simulated only (dry run)")
    return 0


def _cmd_test() -> int:
    return subprocess.call([sys.executable, "-m", "pytest", "-q"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onewrld", description="ONEWRLD system controls")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="check that everything is OK")
    sub.add_parser("status", help="show mode and kill switch")
    k = sub.add_parser("kill", help="STOP all posting and spending")
    k.add_argument("reason", nargs="?", default="manual stop")
    r = sub.add_parser("resume", help="turn the kill switch off")
    r.add_argument("reason", help="why it is safe to resume")
    sub.add_parser("test", help="run all automated tests")
    sub.add_parser("demo-action", help="simulate a post to see the safety gates")
    args = parser.parse_args(argv)

    if args.command == "test":
        return _cmd_test()

    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"Config problem: {e}")
        return 1
    setup_logging(settings.log_dir)

    if args.command == "health":
        return _cmd_health(settings)
    if args.command == "status":
        return _cmd_status(settings)
    if args.command == "kill":
        safety.halt(settings, args.reason)
        print("Kill switch ON. All posting and spending is blocked.")
        return 0
    if args.command == "resume":
        safety.resume(settings, args.reason)
        print("Kill switch off.")
        return 0
    if args.command == "demo-action":
        return _cmd_demo_action(settings)
    return 1
