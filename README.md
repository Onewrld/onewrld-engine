# ONEWRLD Engine

Content, distribution, attribution and paid-ads system for ONEWRLD.

- **How to run, stop, recover:** `RUNBOOK.md`
- **Where the project stands:** `PROJECT_STATE.md`
- **Why things are built the way they are:** `DECISIONS.md`
- **Full plan:** `docs/PHASE0_PLAN.md`

## Code map
| File | What it is |
|---|---|
| `src/onewrld/config.py` | Reads settings from `.env`; the only place settings are defined. |
| `src/onewrld/safety.py` | Kill switch and dry-run gate. Every outward action passes through it. |
| `src/onewrld/logging_setup.py` | Writes logs to the screen and to `logs/onewrld.jsonl`. |
| `src/onewrld/errors.py` | Error types: retryable, permanent, halted. |
| `src/onewrld/health.py` | Health checks behind `python -m onewrld health`. |
| `src/onewrld/db.py` | Connects to the database and applies migrations. |
| `db/migrations/` | Numbered SQL files that create and change tables. Each runs once. |
| `src/onewrld/jobs.py` | The job queue: enqueue, claim, retry and backoff, dead-letter. |
| `src/onewrld/worker.py` | Runs queued jobs; always stops on its own. |
| `src/onewrld/alerts.py` | Records problems you need to know about. |
| `src/onewrld/notify.py` | Emails you alert digests, within hourly/daily caps. |
| `src/onewrld/acceptance.py` | The `phase1-check` drills. |
| `brand/` | Brand bible (voice rules, banned phrases), voice quiz, caption files. |
| `src/onewrld/brand.py` | Scores a caption against the brand bible. |
| `src/onewrld/captions.py` | Imports captions; review with approve/reject/edit and reasons. |
| `src/onewrld/quiz.py` | The voice quiz and your voice profile. |
| `assets/brand/` | Logo files. |
| `assets/fonts/` | Assistant font (open license). |
| `src/onewrld/overlays.py` | Draws caption text, logo watermark and end card; defines the safe zone. |
| `src/onewrld/studio.py` | Renders a clip to a finished 9:16 video; variants; quality gate. |
| `src/onewrld/speech.py` | Speech model (optional): word timings, dead-air cuts, word-by-word captions, .srt files. |
| `brand/hooks.toml` | 110 opening lines (hooks), typed and product-tagged. |
| `brand/formats.toml` | 32 video formats with shot lists. |
| `src/onewrld/shotlist.py` | Builds a shoot-day shot list from the formats. |
| `brand/products.toml` | In-stock products: facts, collection, photo links. |
| `src/onewrld/products.py` | Product catalog and photo downloads. |
| `brand/platforms.toml` | Each platform: handle, daily cap, post times, caption and link rules. |
| `src/onewrld/distribution.py` | Scheduler, per-platform captions, tracked links, post review, daily posting kit. |
| `src/onewrld/adapters.py` | Publishing plug-ins: manual kit today, automatic posting later; all real posts go through the safety gate. |
| `db/portal/` | Affiliate Portal tables, security rules and button functions (Supabase). |
| `portal/` | The Affiliate Portal website (Netlify). `config.js` holds the public Supabase settings. |
| `netlify.toml` | Tells Netlify to publish `portal/`, with strict security headers. |
| `src/onewrld/portal.py` | Portal setup, invites, owner, members. |
| `src/onewrld/videos.py` | Connects the studio to the database and job queue; uses your approved captions. |
| `src/onewrld/handlers/` | The code for each kind of job (demo jobs for now). |
| `src/onewrld/cli.py` | The commands you type. |
| `tests/` | Automated tests. Run them with `python -m onewrld test`. |
