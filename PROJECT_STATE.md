# PROJECT_STATE.md

_Last updated: 2026-11-01_

## Where we are
| | |
|---|---|
| Phase | 1: Foundation |
| Done | Phase 0 plan. Module 1.1 (skeleton and safety). Module 1.2 (database, migrations, job queue, worker, alerts, database kill switch; 33 tests pass against a test database) |
| Current | Owner connects Supabase (RUNBOOK section 6) and runs `migrate` |
| Next | Module 1.3: email alerts and the Phase 1 acceptance test, then Phase 2 (Brand Brain) |
| Blockers | `DATABASE_URL` in the owner's `.env` |

## Phase checklist
- [x] Phase 0: Plan and feasibility
- [ ] Phase 1: Foundation. [x] 1.1 skeleton and safety · [x] 1.2 database and job queue · [ ] 1.3 email alerts and acceptance
- [ ] Phase 2: Brand Brain
- [ ] Phase 3: Video Studio (plus 3.5 manual posting kit)
- [ ] Phase 4: Attribution
- [ ] Phase 4B: Volume Engine
- [ ] Phase 5: Distribution
- [ ] Phase 6: Learning Loop and Dashboard
- [ ] Phase 7: Paid Ads
- [ ] Phase 8: Hardening

## Credentials still needed (names only, never values)
- `DATABASE_URL` (Supabase, new project): now
- Gmail app password for sending alert emails: Module 1.3
- `ANTHROPIC_API_KEY`: Phase 2
- Shopify custom-app Admin API token (read-only): Phase 4
- Meta app and tokens, posting-layer API key, X API keys: Phase 5

## Open questions for owner
- Platform handles (brand and personal) for IG, FB, TikTok, X and YouTube
- Is Instagram a Business or a Creator account?
- Own-drop price, cost per shirt, release cadence; next 2 to 3 drops
- Do gym collabs have a revenue split?
