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

## M-005 (2026-11-01): After the M-004 fix, the owner still saw a kill-switch warning, the job drill failed, and a test failed
- **Root cause, most likely (reproduced here; to be confirmed with `diagnose` from the owner's PC):**
  1. A kill switch left ON by an earlier failed run. Health shows that only as a WARN, but it makes both the kill drill and the job drill fail, with an unclear message ("job queued (None)").
  2. Two tests inspected the real `public` schema, so their result depended on what was in the owner's database. That's the same class of mistake as M-004.
- **Fix:**
  - `phase1-check` now runs a preflight: if there are misplaced tables, an unreachable database or a kill switch already ON, it stops and prints the one command to run.
  - The two tests now use their own empty throwaway schemas.
  - New `diagnose` command: a paste-safe report (kill flags with reasons, where tables live, recent errors, failing tests) so the next problem is diagnosed from facts instead of guesses.
- **Rule added to CLAUDE.md:** tests must never read or write anything outside their own throwaway space.

## M-006 (2026-11-02): `pip install -e ".[dev]"` failed on the owner's PC: "Failed building wheel for pyyaml"
- **Root cause:** Phase 2.1 added the PyYAML package. On the owner's Windows PC, pip found no ready-made download (a "wheel") for his Python version, tried to compile it from source, and failed. My workspace (Linux) had a ready-made download, so I never saw it. The exact trigger (likely a Python version newer than PyYAML's published wheels) is unconfirmed.
- **Fix:** Removed the dependency entirely. The brand files are now TOML (`brand/*.toml`), read by Python's built-in `tomllib`, so there's nothing to install. Data verified identical after conversion. All tests pass with PyYAML uninstalled.
- **Rule added (CLAUDE.md):** prefer Python's built-in modules. Any new package must have a ready-made Windows download for the owner's Python version, or it doesn't go in.

## M-007 (2026-11-02): A commit was pushed with a failing test
- **Root cause:** My commit command ran `python -m onewrld test | tail -1 && git commit …`. A pipe returns the exit code of its LAST command (`tail`, which always succeeds), so the failure didn't stop the commit. The failing test was correct: it caught that two batch-2 captions now break the new "no talking down" ban.
- **Fix:** Removed the 5 owner-rejected captions from the batch-2 file. All my commit commands now run with `set -o pipefail`, so any failure stops the chain. GitHub's automatic test run is the second safety net.

## M-008 (2026-11-02): `render-test` rendered 3 of 4 versions
- **Root cause:** The render command ran the general worker with a budget of 4 jobs. An old leftover job sitting in the queue (from an earlier kill-switch drill) used up one of the 4 slots, so the last render never ran. This would also happen on the owner's PC if old jobs were waiting.
- **Fix:** The worker accepts `only_ids`, and `render` only processes the jobs it just queued. Other queued jobs are left untouched.
- **Test:** `test_worker_only_ids_ignores_unrelated_jobs`.

## M-009 (2026-11-04): Talking clips came out 3 to 4 dB too quiet (quality gate caught it)
- **Root cause:** Single-pass `loudnorm`, and its two-pass "linear" mode, won't add gain when the voice's peaks would exceed the -1.5 dB ceiling. Spoken audio is peaky (about 19 dB between peaks and average), so it stalled around -17.4 LUFS. Test tones (3.1) didn't expose this.
- **Fix:** Voice cleanup (high-pass and 4:1 compression), then measured gain plus a peak limiter (D-046). The quality gate's loudness check is what caught it before any output was used.
- **Test:** `test_talking_clip_renders_with_cuts_and_word_captions` (real synthesized speech must pass the loudness check), `test_two_pass_loudness_uses_measured_values`.

## M-010 (2026-11-04): Black-and-white variants of product photos were near-copies
- **Root cause:** Variant recipes were designed for video. On ONEWRLD's black/white products, the "black and white" variant changes nothing visible.
- **Caught by:** the new similarity check, on its first test run (0 of 64 bits different). Nothing had shipped.
- **Fix:** Photo-specific framing recipes (D-050). Test: `test_batch_renders_products_and_inbox_with_matching_captions` asserts the similarity report is empty.
