# CLAUDE.md: rules for every session on this project

## Project
ONEWRLD growth system: turns short-form video into Shopify sales, profitably.
Full plan: `docs/PHASE0_PLAN.md`. Current state: `PROJECT_STATE.md`.

## Business facts (keep current)
- Brand: ONEWRLD (all caps), Onewrld LLC, Staten Island NY.
- About 75% of drops are ONEWRLD-only collections (for example *Fall of Icarus*). Gym collabs (Intox, Rare Breed) are a small leverage play for reach and events.
- Platforms in use: Instagram, Facebook (linked), TikTok, X, YouTube.
- Stack: Shopify, Enlistly (10% affiliate), Supabase (this project has its own, separate from the partner portal), Netlify.
- Owner: Adam. Windows PC. Full-time job. Beginner coder. Gets overwhelmed quickly. Budget about $1,000.

## How to work with the owner (non-negotiable)
1. One module at a time. After each one: stop, explain it, show it working, get a go-ahead.
2. Define every new term in 1 or 2 plain sentences before using it. Minimal analogies.
3. Every recommendation is written as Decision / Why / What if, and logged in `DECISIONS.md`.
4. Improve on the owner's ideas when a better approach exists; flag additions he didn't ask for.
5. Be direct. Say "I'm not sure" and check current docs instead of guessing.
6. Start and end every session with the "where we are" map (from `PROJECT_STATE.md`).

## Voice rules (all copy and captions)
Natural, not performative. Short. Controlled intensity. Never hype-bro, never corny.
No cringe slang, no emoji spam, no fake urgency. Reads like a serious person wrote it.

## Engineering rules
- MODE defaults to `dry_run`. Every post, spend, or send goes through `safety.outward_action()`.
- Kill switch (`python -m onewrld kill`) beats everything.
- Secrets only in `.env` (git-ignored). Never in code, docs, or commits.
- Every module has tests; `python -m onewrld test` runs them all.
- No unbounded loops, spend, or posting. Jobs must be idempotent (running twice never double-posts).
- No scraping, browser bots, fake engagement, or hidden-ownership accounts.

## Session protocol
Start: read CLAUDE.md, PROJECT_STATE.md, DECISIONS.md, LESSONS.md, MISTAKES.md; print the map; state the single next step.
End: update PROJECT_STATE.md, DECISIONS.md, MISTAKES.md (and LESSONS.md once data exists).
