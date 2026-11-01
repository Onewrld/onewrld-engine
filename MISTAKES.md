# MISTAKES.md

Every failure gets: what happened · root cause · fix · regression test that prevents it.

## M-001 (2026-11-01): `python3 -m venv -q` failed
- **Root cause:** the `venv` command has no `-q` (quiet) flag.
- **Fix:** removed the flag. The RUNBOOK uses the correct command.
- **Test:** n/a (setup command, not system code).

## M-002 (2026-11-01): Owner's first edit of `.env` went wrong
- **Root cause:** hand-editing in Notepad is easy to get wrong (stray characters, lost lines).
- **Fix:** gave a one-paste PowerShell command that rewrites the file cleanly.
- **Prevention:** future settings changes come as a one-paste command where possible.

## M-003 (2026-11-01): Before `migrate`, the kill switch showed ON with an unclear reason
- **Root cause:** the database kill-switch check fails closed when the table is missing, which is correct, but the message just said "UndefinedTable".
- **Fix:** the message now says "run `python -m onewrld migrate`". RUNBOOK section 8 explains it.
- **Test:** `test_unreachable_database_fails_closed` covers the fail-closed behavior.
