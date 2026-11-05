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

## D-032: The brand scorer is rule-based, with a quality floor of 70
- **Decision:** Banned phrases block a caption outright (score 0). Soft rules (exclamation marks, emojis, hashtags, all-caps, length, question hooks) subtract points. A caption must score 70 or more to reach your review queue.
- **Why:** Free, instant, predictable, and you can read exactly why a caption scored what it did. Rules catch what's *wrong*. Taste (corny vs. good) is your call during review, and your reasons get stored.
- **What if:** Rules can't judge taste: "Burned once. Built twice." scores 100 but may be corny. Once there are enough of your approve/reject reasons, we add a taste check learned from them (Phase 6), optionally AI-assisted when the API key is on.

## D-033: Caption decisions use the shared `approval` table
- **Why:** One approvals inbox for captions now, and posts and ad changes later, so the future dashboard has one place to show "waiting for you."
- **Edits:** Your edit saves the original as rejected (with your reason) and your version as approved, linked together. That before/after pair is the strongest learning signal there is.

## D-034: The seed caption bank includes deliberately bad captions
- **Why:** It proves the scorer blocks them ("No days off. Built different. 🔥🔥", "Last chance… !!"), and two borderline ones test where your line is. They're labeled in the caption file.

## D-035: Brand files use TOML, not YAML
- **Why:** TOML is read by Python's built-in `tomllib`, so there's nothing to install and no build failures on Windows (M-006). It's just as readable: text in quotes, lists in brackets, `#` for notes.
- **What if:** If a file has a typo, the error names the line. Run `python -m onewrld captions score "test"` after editing the brand bible to check it still loads.

## D-036: Each collection's meaning is stored in the brand bible, in the owner's words
- **Why:** Batch 1 failed because I guessed what Fall of Icarus means (6/6 story captions rejected). The meaning is now a field (`[collections.fall_of_icarus]`) that every future caption writer, human or AI, must follow, with a list of angles to avoid.
- **What if:** For the December drop, we capture its meaning BEFORE writing a single caption.

## D-037: Caption review shows the newest batch first
- **Why:** So the owner always reviews the latest, best-informed captions first. Older pending ones still come after.

## D-038: Phase 3 is split: 3.1 (format, brand, quality gate, variants) then 3.2 (spoken word-by-word captions and dead-air cuts)
- **Why:** 3.2 needs a speech-recognition model (faster-whisper: a free model that runs on your PC). It's big and needs its own install check on Windows. 3.1 is useful on its own today for product and b-roll clips, which mostly have no talking.
- **What if:** If the speech model is too slow on the PC, 3.2 falls back to a paid transcription service (pennies per minute), with approval first.

## D-039: On-screen text and the logo are drawn with Pillow, not ffmpeg's text tool
- **Why:** ffmpeg's text tool needs font file paths written in a special escaped format that breaks on Windows. Pillow (an image library with ready-made Windows installs) draws a transparent image and ffmpeg lays it on top. Same result, no Windows path problems.
- **Font:** Assistant (your website font), open license, included in `assets/fonts`. The gothic logo font is used only as the logo image.

## D-040: Safe zone and loudness standards
- **Safe zone:** text and logo stay inside x 60 to 930, y 250 to 1420 of the 1080x1920 frame, away from the app buttons on the right and the caption and music bar at the bottom. The quality gate checks the caption's position.
- **Loudness:** -14 LUFS (the common streaming loudness standard), peaks capped at -1.5 dB. Every clip plays at the same volume as the content around it.
- **What if:** If a platform changes its interface, edit `SAFE` in `overlays.py`; the tests check that every caption fits inside.

## D-041: Variants change several things at once
- **Decision:** Each variant changes 2 to 4 of: look (natural or black-and-white), crop position, slow zoom, length, caption.
- **Why:** Platforms fingerprint footage. A variant must be meaningfully different, not a recolor. Black-and-white is on-brand (your palette). These variants are for TESTING which treatment works (D-008); the strongest gets posted per platform.
- **What if:** Once the learning loop (Phase 6) has data, it picks the treatments that perform best.

## D-042: Build order after 2026-11-04 (owner approved)
3.2 speech → 4B Volume Engine → 5 Posting → 4 Sales tracking → December drop. The owner **declined** the AI writer key for now (D-029 stands): captions keep coming from build sessions at $0. Shoot: weekend of 2026-11-07.

## D-043: Speech is an optional install; Python 3.11 to 3.14 recommended
- **Why:** The speech model needs `onnxruntime`, which has no Windows install for Python 3.15 yet. The owner's PC is almost certainly on 3.15 (PyYAML's failure points to it). Making speech optional means the core system never breaks because of it; the health check says exactly what to do.
- **What if:** If adding Python 3.13 is a problem, wait for onnxruntime to support 3.15 (usually a few months), or use a paid transcription service (a few cents per minute, with approval first).

## D-044: Word-by-word captions use ASS subtitles, run with relative file names
- **Why:** ASS is the standard styled-subtitle format, and ffmpeg burns it in fast and sharp. Running ffmpeg *inside* the work folder and naming files without a drive letter avoids the Windows `C:` path problem (same problem as D-039).
- **Look:** 4 words on screen at most, a new line at each sentence end, the current word white and the others gray (your black-and-white palette), centered in the safe zone.

## D-045: Dead-air cut rule: pauses over 0.6 s go, 0.12 s of air kept around speech
- **Why:** Tight pacing holds attention on short-form; 0.12 s of padding stops words from being clipped.
- **What if:** If cuts feel too jumpy, raise `MAX_GAP` in `speech.py` (for example to 0.9).

## D-046: Loudness = voice cleanup, then measured gain, then a peak limiter
- **Decision:** Pass 1 measures the cleaned audio. Pass 2 applies the exact gain needed for -14 LUFS, then a limiter at -1.5 dB. Single-pass leveling remains as a fallback.
- **Why:** M-009: ffmpeg's leveler undershoots by 3 to 4 dB on peaky voice. Measured: test tone -14.0, synthetic voice -16.4 (inside the quality gate's +/-3). A real voice should land closer to -14; we confirm on the first real footage.

## D-047: Render fingerprints include a pipeline version
- **Why:** Re-rendering the same clip reuses the old file (idempotency). When the pipeline itself improves, the version bump makes it render fresh.

## D-048: Phase 4B starts with the content that already exists (owner, 2026-11-04)
- **Decision:** 4B.1 makes videos from the store's product photos and from anything dropped in `media/inbox`, before the shoot. Talking-clip slicing (4B.2) builds on the shoot footage.
- **Why:** The owner asked to build from the content he has now. Product photos give 4 videos per photo today (6 photos = 24 videos) at $0.
- **What if:** Product photos are the weakest content type (static; real footage converts better). They fill the calendar while the shoot footage gets cut.

## D-049: Captions are matched to products
- **Decision:** Each caption carries a `product` tag: a product handle, `collection:<name>`, or `brand`. A video of a product only uses captions for that product, its collection, or brand-wide lines. Untagged footage can use any approved caption.
- **Why:** A sweatpants line on a hat video is wrong content, and a customer would notice. Tags live in the caption files; re-importing refreshes the tags without touching approvals.

## D-050: Photos get framing variants, not color variants
- **Why:** ONEWRLD's products are black and white, so a black-and-white version of a product photo is identical to the original. The new similarity check caught this on its first run (M-010). Photo variants change framing instead: whole product, closer detail, tight detail, short and off-center. Photos also always drift slowly, so they never look frozen.
- **Caption on photos:** sits under the product, with a soft dark band behind it for readability.

## D-051: Near-duplicate check uses a perceptual "difference hash"
- **What it is:** a 64-bit fingerprint of what a frame looks like. Similar images give similar fingerprints. Two versions of one source that differ by 5 bits or fewer AND share a caption are flagged.
- **Why:** Platforms fingerprint footage the same way; we catch near-copies before they do. Built with Pillow, no new package.

## D-052: Phase 5 starts with a manual posting kit behind an adapter interface
- **Decision:** 5.1 schedules, captions, links and approves posts, then exports a daily kit for posting by hand. Automatic posting comes in 5.2 as an "adapter", a small plug-in with one job: publish a post.
- **Why:** Posting by hand from a ready kit takes about 2 minutes per post and works today, with no accounts to connect and no monthly fee. The posting-service decision (cost, TikTok and YouTube approval) gets made with real posts running. All automatic adapters go through `safety.outward_action`, so the kill switch and dry-run cover every real post.
- **What if:** If posting by hand is too slow, approve the posting-service cost and 5.2 switches the adapter. Nothing else changes.

## D-053: Scheduling rules
- 1 post a day per platform to start (D-031), at times from `platforms.toml`.
- The same footage at most once a week per platform; each platform gets a different version of a clip where one exists.
- The least recently used footage goes first, so everything gets rotated.
- Missed posts expire after a day instead of piling up.
- **Post times are starting guesses, not proven:** TikTok 7pm, Instagram 12pm, X 12:30pm, Facebook 1pm, YouTube 3pm (Eastern). Phase 6 replaces them with what ONEWRLD's own data shows.

## D-054: Links
- **Tappable links** (YouTube, Facebook, X): every post carries its own tracked link (UTM tags: source = platform, campaign = collection, content = post number) to the matching product page.
- **Instagram and TikTok:** no link in the caption (it can't be tapped there, and your quiz said no calls to action). A tracked bio link per app instead (RUNBOOK 16).
- Shopify keeps the UTM tags on each order's landing page, so Phase 4 can match orders to posts and platforms.

## D-055: `tzdata` added as a dependency
- **Why:** Windows has no built-in time-zone database, so scheduling in Eastern time would fail on the owner's PC. `tzdata` is pure Python with ready-made installs for every version (rule M-006 satisfied).

## D-056: The hook library: 110 hooks in 9 types, approved like captions
- **What a hook is:** the opening line of a video (the first 1 to 2 seconds). On short-form, this decides whether anyone watches the rest.
- **Types:** statement, founder, process, product detail, icarus (pride before the fall), discipline, contrast, list, POV. Every hook passes the brand rules and fits LESSONS L-001 to L-007; none are questions (the quiz said statements).
- **Stored with captions** (kind = hook): same scoring, approval and feedback. The same words can be approved separately as a hook and as a caption.

## D-057: On screen = a hook; post text = a caption; each version gets a different hook
- **Why:** This turns every clip into a built-in test of which hooks work. The video records `hook_id` and `format_id`, so the learning loop (Phase 6) can compare them on real views and sales.
- **What if:** If no hooks are approved yet for a product, the caption goes on screen as before.

## D-058: Format library (32) and shot list generator
- **Formats:** each has a location, length, filming time, products, suited hook types and a shot list. Priority right now: talking clips (one talk becomes many posts), then Fall of Icarus product details, packing, the full set, the gym.
- **Shot lists** fit the time you have, skip products that are out of stock, group by location (15 min allowed per location change), and suggest unique, product-matched hooks per format.
- **What if:** If a format underperforms, Phase 6 drops it down the priority list.
