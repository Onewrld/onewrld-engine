# MISTAKES.md

Every failure gets: what happened · root cause · fix · regression test that prevents it.

## M-001 (2026-11-01): `python3 -m venv -q` failed
- **Root cause:** the `venv` command has no `-q` (quiet) flag.
- **Fix:** removed the flag. The RUNBOOK uses the correct command.
- **Test:** n/a (setup command, not system code).
