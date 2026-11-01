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

## M-004 (2026-11-01): On the owner's PC, tests and the kill-switch drill failed. Tables were in the wrong schema.
- **What happened:** `phase1-check` on the owner's PC: tests failed and the kill-switch drill failed. My workspace passed everything.
- **Root cause:** `db.connect` set the schema with a connection option (`options=-c search_path=...`). Supabase's connection pooler (Supavisor) ignores that option (an open Supavisor bug report, issue #206, describes the same thing), so on the owner's PC every table went into Supabase's default `public` schema. Two effects:
  1. The tests' throwaway schemas didn't isolate anything. Tests ran on the same `public` tables as the real system, so counts were wrong, and a failed test could leave the **real** kill switch ON.
  2. That leftover ON flag made the drill fail.
  My workspace connects directly (no pooler), so the option worked there and the bug was invisible. **Lesson: the test setup must match production. Never trust a connection setting without verifying it.**
- **Fix:**
  - `connect` now runs an explicit `SET search_path`, then **verifies** it, and refuses to continue if it doesn't match.
  - Transaction-pooler URLs (port 6543) are refused, because they reset the setting.
  - A `repair-schema --yes` command removes only our own named tables from `public`, and only if `public.schema_migrations` proves they're ours. Then it recreates them in `engine`.
  - `health` fails loudly if misplaced tables exist.
- **Regression tests:** `test_schema_is_set_explicitly_and_verified`, `test_transaction_pooler_url_is_refused`, `test_repair_removes_only_our_misplaced_tables`, `test_repair_refuses_active_schema`. A guard in `conftest.py` aborts any database test whose tables aren't in its own throwaway schema.
