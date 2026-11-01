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

## D-003: Postgres-backed job queue (no Redis)
- **Decision:** Jobs live in the database (library: Procrastinate, confirmed in Module 1.2).
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
