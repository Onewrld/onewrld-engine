# DECISIONS.md

Every decision is written as Decision / Why / What if. Newest at the bottom.

## D-001: Unified posting layer for TikTok, YouTube (and Pinterest later)
- **Decision:** Publish to these through a hosted posting API whose apps are already approved. Integrate Meta, X and Shopify directly.
- **Why:** Unaudited TikTok and YouTube apps can only post privately, and their audits take weeks with uncertain outcomes.
- **What if:** If the vendor fails or raises prices, swap the one adapter file. Manual-post fallback always exists. We can apply for our own audits later.

## D-002: Separate Supabase project for this system
- **Decision:** New Supabase project; don't share the partner-portal one.
- **Why:** A bug or schema change here can never break the partner portal. Free tier allows it.
- **What if:** If we hit free-tier limits, upgrade this project only ($25/mo), or move the plain Postgres schema elsewhere.

## D-003: Postgres-backed job queue (no Redis). REVISED in 1.2, see D-015
- **Decision:** Jobs live in the database.
- **Why:** One less service to run and pay for; jobs are visible in the Supabase table viewer; survives restarts.
- **What if:** If it ever bottlenecks, move jobs to a dedicated queue; job code is plain functions.

## D-004: Local transcription (faster-whisper)
- **Decision:** Transcribe on the owner's PC.
- **Why:** Free, private, word-level timestamps for captions.
- **What if:** Too slow or inaccurate → hosted API (one setting).

## D-005: Video files in Cloudflare R2, not Supabase storage
- **Decision / Why:** Video is large; R2 has no download fees. **What if:** local disk plus Drive backup.

## D-006: Paid ads stay recommend-only in v1
- **Why:** At this budget a wrong automated action costs more than the time saved. **What if:** revisit at $3k+/mo spend with 90 days of history.

## D-007: Only openly-owned accounts
- **Why:** Hidden-ownership pages break Meta's inauthentic-behavior rules and FTC rules → ban risk. **What if:** a niche page is always labeled "a ONEWRLD page."

## D-008: Variants are for testing, not flooding
- **Why:** Platforms fingerprint footage; overlay-only variants read as duplicates. Publish the best 1 to 3. **What if:** if data shows more variants per footage hold reach, raise the cap.

## D-009: Phase 3.5 manual posting kit, and tracked links from the first post
- **Why:** Learning starts when posts go live, not when automation is finished. **What if:** none; it's additive.

## D-010: Own drops lead; gym collabs are a leverage track
- **Why:** About 75% of drops are ONEWRLD-only, and ONEWRLD keeps the full margin on them. **What if:** if collabs grow, change the weights in config.

## D-011: Kill switch is a file (`state/KILL`), checked before every outward action
- **Decision:** A flag file; checked first, before the dry-run check, in every mode.
- **Why:** It works even if the database or internet is down. It's simple enough to verify by looking in a folder.
- **What if:** If the file is deleted by accident, the system resumes, so resume normally requires a reason and is logged. In Module 1.2 a database flag is added too, so the dashboard can show and flip it.

## D-012: MODE defaults to dry_run
- **Why:** A missing or typo'd setting can never cause a real post or spend. An invalid MODE refuses to start.
- **What if:** If you want real actions, set `MODE=live` explicitly. `health` warns whenever live is on.

## D-013: Plain Python virtual environment now, Docker later
- **Decision:** Phase 1 runs in a Python venv on the Windows PC. Docker is added once we have a database and a worker to run together.
- **Why:** On Windows, Docker needs WSL2 setup. A venv gets you running today with fewer moving parts.
- **What if:** If Docker turns out smoother on your PC, switch then; the code doesn't change.

## D-014: The command line is `python -m onewrld <command>`, not `make`
- **Why:** `make` doesn't exist on Windows by default. Python commands work everywhere.
- **What if:** none.

## D-015: A small custom job queue (~200 lines) instead of the Procrastinate library
- **Decision:** One `job` table plus `jobs.py`, using Postgres `FOR UPDATE SKIP LOCKED` (a standard database feature that lets several workers take jobs without ever taking the same one).
- **Why:** You can read every line and see every job in the Supabase table viewer. It has no async code and no extra schema to learn. It covers exactly what we need: idempotent enqueue, retries with backoff, dead-letter, crash recovery. This replaces the earlier plan (D-003) to use Procrastinate, because that library brings concepts you don't need yet.
- **What if:** If we need scheduling features beyond Phase 5's simple scheduler, or many workers, move to Procrastinate. Handlers are plain functions, so they port unchanged.

## D-016: Our tables live in a separate schema `engine`, with Row Level Security on
- **Why:** Supabase's public web API only exposes the `public` schema. Keeping our tables in `engine` means your anon/public key can never read jobs, alerts or orders. RLS is a second lock.
- **What if:** When the dashboard needs data (Phase 6), we add specific read-only views or policies on purpose, never by opening tables.

## D-017: The kill switch fails closed
- **Decision:** If the database is configured but unreachable (or not migrated), the system treats itself as halted.
- **Why:** When unsure, stop. A missed post costs nothing; an unwanted post or spend can't be undone.
- **What if:** If the database is down for a long time, nothing posts. That's intended. `health` tells you why.

## D-018: Each job's work runs outside a database transaction
- **Why:** If a post goes out and the database then fails, a rollback would "forget" a post that really happened, and a retry would double-post. So the work runs first, and the result is recorded afterwards in its own transaction.
- **Known gap (handled in Phase 5):** if the PC crashes in the second between a real post and its recording, the job is retried after 30 min. Phase 5 posting jobs will check the platform or posting layer for an existing post before posting again.

## D-019: Tables are added by the module that uses them, not all at once
- **Decision:** 1.2 creates only the core tables (job, alert, approval, system_flag). Content, post, order and similar tables arrive with their modules.
- **Why:** Designing 22 tables before we know what each module needs leads to rework. Each table gets explained as it arrives.
- **What if:** none; migrations make adding tables routine.

## D-020: Supabase "Session pooler" connection, not direct
- **Why:** Supabase's direct connection is IPv6-only on the free plan (as far as I know; confirm when you connect), and many home ISPs are IPv4. The session pooler works on both.
- **What if:** If the session pooler causes issues, try the direct string; the code works with either.

## D-021: Database tests run in a throwaway schema
- **Why:** You can run the full test suite against your real Supabase without any risk to the real `engine` tables. Each test creates `test_xxxxxxxx`, then deletes it.
- **What if:** If tests are interrupted mid-run, a leftover `test_...` schema may remain. It is safe to delete in Supabase.

## D-022: Keep the owner's GitHub Actions workflow, fixed so it can pass
- **Decision:** Kept your `python-package.yml` and changed it to test Python 3.12 and 3.13, install the project first, and start a throwaway Postgres database so the database tests run too.
- **Why:** As written it tested Python 3.9 and 3.10 (the project needs 3.11+) and never installed the project, so it would always show a red X. Automatic tests on every push catch breakage before it reaches your PC.
- **What if:** If GitHub shows a red X, open the failed run and paste the red error text to Claude. Free GitHub accounts include monthly Actions minutes; this run takes about 1 to 2 minutes.
