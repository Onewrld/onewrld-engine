# PROJECT_STATE.md

_Last updated: 2026-11-05_

## Where we are
| | |
|---|---|
| Phase | 5: Distribution |
| Done | Phase 0 plan. Module 1.1 (skeleton and safety). Module 1.2 (database, job queue, worker, alerts, database kill switch). Module 1.3 (email alerts with caps, log rotation, `phase1-check`; 43 tests pass) |
| Current | Hook & Format Library built. Owner: captions import → hooks review; shotlist for the weekend shoot |
| Next | 5.2: automatic posting adapter (posting service + Meta direct), cost approval first. 4B.2 talking-clip atomizer after the shoot and the Python 3.13 fix |
| Blockers | **Checkout converts 1 in ~19** (store audit 2026-11-05): fix shipping surprise, turn on abandoned-checkout emails, check wallets, phone test purchase. Highest-value fix in the business right now |

## Phase checklist
- [x] Phase 0: Plan and feasibility
- [x] Phase 1: Foundation (owner's PC reported good on 2026-11-02, after fixes M-004 and M-005). [x] 1.1 skeleton and safety · [x] 1.2 database and job queue · [x] 1.3 email alerts and acceptance (owner to run `phase1-check`)
- [ ] Phase 2: Brand Brain. [x] 2.3 hook library (110) + format library (32) + shot list generator · [x] 2.1 bible, scorer, quiz, caption bank (30), review with feedback · [x] owner test: 10 reviewed (4 approved, 6 rejected) · [x] 2.2 batch 2 written from the owner's reasons · [x] owner reviewed 10 of batch 2 (5/10) · 11 left to review whenever
- [ ] Phase 3: Video Studio. [x] 3.1 9:16 reframe, logo, captions, end card, loudness, variants, quality gate, render-test (verified on owner's PC) · [x] 3.2 word-by-word captions, dead-air cuts, .srt, voice audio chain (blocked on owner's PC: Python 3.15.2 has no onnxruntime; fix = RUNBOOK 14) · [x] 3.5 posting kit (built as part of 5.1)
- [ ] Phase 4B: Volume Engine. [x] 4B.1 product photos to video, inbox batch, product-matched captions, similarity check · [ ] 4B.2 talking-clip atomizer
- [ ] Phase 5: Distribution. [x] 5.1 platforms, scheduler (caps, spacing, variant spread), captions per platform, tracked links, approval, posting kit, adapter interface · [ ] 5.2 automatic posting
- [ ] Phase 4: Attribution (after 5, before the drop)
- [ ] Phase 6: Learning Loop and Dashboard
- [ ] Phase 7: Paid Ads
- [ ] Phase 8: Hardening

## Credentials still needed (names only, never values)
- `DATABASE_URL`: done
- `SMTP_USER`, `SMTP_APP_PASSWORD` (Gmail app password): now
- `ANTHROPIC_API_KEY` (with a monthly spend limit): deferred to Phase 4B/5 (D-029)
- Shopify custom-app Admin API token (read-only): Phase 4
- Meta app and tokens, posting-layer API key, X API keys: Phase 5

## Open questions for owner
- Photo-to-video: off after owner rejected it (M-011); reference video formats still wanted
- Personal/founder handles (brand handles found: IG @onewrld.us, TikTok @onewrld.US, X @onewrldus, YT @onewrldus)
- Is the font in the logo/graphics the same as the website font (Assistant)?
- Next drop (about mid-Dec): name and what it means
- Is Instagram a Business or a Creator account?
- Own-drop price, cost per shirt, release cadence; next 2 to 3 drops
- Do gym collabs have a revenue split?
