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

## D-023: Alert emails go through Gmail SMTP with an app password
- **Why:** Free, uses the account you already have, and nothing to verify (no domain setup). Python's built-in `smtplib` sends it, so there's no extra dependency.
- **What if:** If Gmail blocks it or you want SMS, switch to a sending service (for example Resend or Twilio) by changing only `notify.send_email`. If the app password leaks, revoke it in Google; nothing else is exposed.

## D-024: Alert emails ignore the kill switch and dry-run mode
- **Why:** They only ever go to you, and you need them most when the system is stopped or failing. The kill switch is for posting and spending.
- **What if:** If they become noise, the caps (D-025) and the digest bundling limit them. Never route customer-facing email through this path.

## D-025: Alerts are bundled into digests, capped at 4/hour and 20/day
- **Why:** A burst of failures must not flood your inbox, or you'll start ignoring it. Held-back alerts wait for the next digest, so none are lost. Only warn/critical are emailed; info goes in the Monday memo.
- **What if:** If 4/hour is too few during a crisis, run `python -m onewrld alerts` to see everything; adjust the caps in `notify.py`.

## D-026: Log files rotate at 5 MB, keeping 5
- **Why:** "No unbounded anything" applies to disk too. 30 MB max of logs.
- **What if:** If we need longer history, alerts and jobs are already kept in the database.

## D-027: Secrets are hidden when settings are printed
- **Why:** If settings ever get printed or logged, the database URL and app password are left out, so a pasted error can't leak them. A test enforces this.

## D-028: Schema is set by an explicit command and verified on every connection
- **Why:** Bug M-004: a connection option was silently ignored by Supabase's pooler. Explicit `SET` + check means a wrong schema causes an error, never silent damage.
- **What if:** If we ever must use the transaction pooler (port 6543), switch to fully qualified table names (`engine.job`). Until then, port 6543 is refused.

## D-029: No paid AI key yet. Phase 2 is built so the paid part is optional.
- **Decision:** Build Phase 2 without an Anthropic API key. The brand bible, banned-phrase checks, rule-based scoring, hook library, approval flow and feedback capture are all plain code and cost $0. The first caption batches and the hook library are drafted by Claude in these build sessions (covered by the owner's existing Claude plan), loaded into the database, scored, and approved or rejected by the owner.
- **Why:** The only part that truly needs a paid key is the system writing captions *on its own, unattended, at volume*. That doesn't matter until automated publishing (Phases 4B and 5). Paying now buys nothing we can't do for free yet, and the budget is tight.
- **What if:** When automated generation is needed, add `ANTHROPIC_API_KEY` with a hard monthly limit (estimated $5 to $15/mo). The generator is written behind one function, so switching it on is a settings change, not a rebuild. If that cost is ever unwanted, the system keeps working on human-written or session-drafted captions; it just produces fewer variants.

## D-030: Reorder the build around the December drop
- **Decision:** Order is now 2-lite (voice quiz, caption bank, banned phrases, scoring) → shoot day → 3 (Video Studio) → 3.5 (manual posting kit with tracked links) → 4-lite (Shopify sales attribution) → December drop. Automated publishing (5) and ads (7) come after the December drop.
- **Why:** The owner wants heavy volume now, and the bottleneck is footage and editing, not automation. Manual posting starts as soon as the first videos are cut; automation can't help before content exists.
- **What if:** If the shoot slips, Phase 3 slips with it. That's the one dependency to protect. Fallback: post existing product photos and old clips with new captions.

## D-031: Volume with per-platform caps
- **Decision:** Heavy volume = the same strong video posted once on each of IG, TikTok, YouTube Shorts and FB (plus a text version on X), at 1 to 3 different videos per day. That's 5 to 15 posts a day across platforms.
- **Why:** Posting the same video on different platforms is normal and safe. Reposting near-copies on the SAME platform triggers originality penalties (Instagram April 2026 rule; TikTok and YouTube similar).
- **What if:** If reach per post holds, raise to 3 to 5 videos a day; if it drops, pull back.
