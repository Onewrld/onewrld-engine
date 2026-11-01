# ONEWRLD Growth System: Phase 0 Plan and Feasibility Report

Date: 2026-11-01 · Status: Phase 0 (planning). No code yet. Waiting for owner go-ahead.

Sourcing rule: anything marked **[verified]** was checked against official docs or several current sources today. Anything marked **[unverified]** I believe but have not confirmed. I will check it before building on it.

---

## Where we are

| | |
|---|---|
| Done | Read the brief. Researched current platform API rules. |
| Current | Phase 0: this plan. |
| Next | Phase 1: Foundation (repo, database, logging, dry-run, kill switch, health check). |
| Blockers | Your answers to the 5 Phase-1 items in Section 2. |

---

## 1. The project in my words (under 150 words)

ONEWRLD sells mostly its own limited collections (about 75% of drops, for example *Fall of Icarus*). Gym collabs are a small leverage play for reach and events. Right now each drop depends on in-person events and your own hours. You want a system that turns a small amount of filmed footage into a steady flow of distinct, on-brand short videos and posts. Those go out across the brand account, your founder account, partner gyms and affiliates. Every post carries a tracked link, so each sale traces back to the post, platform, gym or affiliate behind it. The system learns which hooks and formats actually make money, as opposed to views. It only spends ad money on proven winners, inside hard caps you approve. It must run on about $1,000, a few hours a week of your time, and skills you are still building. So it has to be modular, safe by default (dry-run, approvals, kill switch) and explained as we go.

---

## 2. What I need from you

**Phase 1 blockers (needed before I write code):**

1. **Your computer.** Mac or Windows, and roughly how old. Video rendering is heavy, and I need to know whether your machine can do it or we need a cloud box.
2. **A GitHub account.** This is where the code lives and is backed up. Free.
3. **Supabase decision and access.** I recommend a *new, separate* Supabase project for this system and leaving the partner-portal project alone (see the decisions log below). You create it, then put the URL and keys into a `.env` file yourself. I will show you how. I never need to see the values.
4. **An alert email address**, where the system sends errors and the Monday memo.
5. **Which platforms you actually use today, with handles**, for both the brand and your personal account. Also: is the Instagram account a Business or Creator account, and is it linked to a Facebook Page?

**Needed later (not blocking):**

| # | Item | Needed by |
|---|---|---|
| 6 | Brand assets: logo files (SVG/PNG), font files or font names, exact brand colors, any existing captions you're proud of, and 5 you hate | Phase 2 |
| 7 | An Anthropic API key with a spend limit set, for captions and scoring | Phase 2 |
| 8 | Sample raw footage: one 10 to 20 min talking or founder clip, one gym or event clip, and one product or packing clip, filmed vertically if possible | Phase 3 |
| 9 | Shopify: create a custom app with read-only scopes (orders, products, inventory, discounts, customers) | Phase 4 |
| 10 | Unit economics per SKU: product cost, average shipping cost, packaging, and your Shopify plan and payment fee rate | Phase 4 |
| 11 | Enlistly: can you export affiliates and codes, and does your plan include API or webhook access? **[unverified]** I don't know whether Enlistly has a public API. | Phase 4 |
| 12 | Your email and SMS tool (Shopify Email, Klaviyo, other?) | Phase 4 |
| 13 | Meta Business Manager, Facebook Page, IG Business account and ad account, with you as admin | Phase 5 |
| 14 | TikTok Business account and TikTok Ads Manager | Phase 5 / 7 |
| 15 | YouTube channel | Phase 5 |
| 16 | A list of collab gyms, their handles, and whether they agree to receive weekly content packs | Phase 4B |
| 16b | Your own-drop history: past drops (name, date, price, units, sold-out yes/no), typical release cadence, and the next 2 to 3 planned drops | Phase 2 (content calendar) and Phase 4 |
| 17 | Music approach: original audio only, or a licensed library subscription | Phase 3 |
| 18 | A short domain or subdomain for tracked links (for example `go.onewrld.com`) | Phase 4 |

---

## 3. Feasibility Report

### 3.1 Platform API reality (as of Nov 2026)

| Platform | Can we auto-publish? | Gate | Time to unlock | Cost | Verdict |
|---|---|---|---|---|---|
| **Instagram (Reels, posts, carousels)** | Yes, through the Graph API, for Professional accounts. **[verified]** | A Meta developer app. For accounts you own and admin, I believe no full App Review is needed. **[unverified]** | Days | Free | **Priority 1.** Cap is 100 API posts per account per rolling 24h; read the live cap from the `content_publishing_limit` endpoint, because some docs still say 50. **[verified]** |
| **Facebook Page (Reels, posts)** | Yes, same Meta app | Same | Days | Free | Priority 4 (low effort, low return) |
| **TikTok** | Only after an audit. Unaudited apps post **private-only**, for at most 5 users per 24h. **[verified]** | TikTok audit, typically 2 to 4 weeks, often rejected. A single-brand internal tool may not pass. | Weeks, uncertain | Free | **Priority 1, but through a unified posting layer (its app is already audited) or the "upload to drafts" flow. Do not build direct.** |
| **YouTube Shorts** | Only after a compliance audit. Uploads from unverified projects are locked private, and that cannot be appealed. **[verified, consistent across sources]** | Google API audit | Weeks | Free | Priority 2. Use the unified layer. |
| **Threads** | Yes, Meta API | Meta app | Days | Free | Priority 3 (text and repurposed posts) |
| **X** | Yes | Pay-per-use since Feb 2026, about $0.01 per post created. **[verified across several sources; confirm on X's pricing page]** | Immediate | About $1 to $5/mo at our volume | Priority 5. Cheap, but low return for apparel. |
| **Pinterest** | Trial access creates sandbox pins only you can see. Public pins need Standard access. **[verified]** | Standard access review; community reports waits of weeks to a month or more | Weeks | Free | Priority 6. Evergreen product discovery. Use the unified layer. |
| **Snapchat Spotlight** | **[unverified]** I don't believe there is an open public posting API for Spotlight. | Partner-only | n/a | n/a | **Skip for now.** Post manually if ever. |

**Critical finding you didn't ask about: trending audio.** Posting APIs generally can't attach a platform's in-app music library. **[unverified for every platform; I'll confirm per adapter]** Any video posted through an API must carry its audio baked in: your voice, original audio, or licensed music. Trending sounds therefore require a 30-second manual finish in the app. The design handles this: trend-jack videos go to TikTok drafts or a phone handoff, and evergreen videos auto-publish with original or licensed audio.

### 3.2 Duplicate and low-effort suppression (it's real and getting stricter)

- **Instagram (Apr 2026):** Accounts that mainly post unoriginal content are removed from recommendations, which covers Reels, photos and carousels. Watermarks, speed changes, borders and credit lines don't count as "material edits." **[verified]**
- **YouTube (Jul 2025):** The "inauthentic content" policy covers templated, mass-produced, little-variation content, especially Shorts. The enforcement detail is mostly about monetization, but repetitive templates are clearly the target. **[verified]**
- **TikTok:** Unoriginal or reuploaded content is ineligible for the For You feed. Repeated flags can make a whole account ineligible for a period. **[verified that the policy exists; exact thresholds unverified]**

**What this means for the Volume Engine:** Your instinct is right that variants beat copies. But your remix matrix (same footage with a different hook overlay, crop or color) is exactly the pattern these classifiers are built to catch, because platforms fingerprint the footage. Changing the text on top doesn't make it new. So the design rules are:

1. **Most differentiation comes from the footage itself:** a different segment, a different moment, a different angle. Packaging is secondary.
2. **Remix variants are mainly a testing tool.** Generate 20, score them, publish the best 1 to 3. The rest stay in the archive or become ad creative.
3. **The same source footage never goes to two of our own accounts on the same platform within N days**, and N is learned. The perceptual-hash filter enforces this inside our system, as a stand-in for what the platforms check.

### 3.3 Buy vs build for posting

**Decision:** Use a hosted unified posting API for publishing to TikTok, YouTube and Pinterest. Integrate Meta (Instagram, Facebook, Threads) directly for analytics, and possibly for publishing once that is proven. Integrate Shopify and the ad platforms directly.

**Why:** TikTok, YouTube and Pinterest all lock unaudited apps into private or sandbox posting. A hosted layer has already passed those audits, which saves weeks of approval risk on day one. **Self-hosted Postiz doesn't solve this**, because it uses *your own* developer apps, so the audits are still yours. Ayrshare starts at about $129 to $149/mo per source, which doesn't fit a $1,000 budget.

**Shortlist to price-check before you approve:** Postiz Cloud (open-source core, has an API, and there is a Postiz skill available in this environment), Upload-Post, bundle.social, Zernio/Late, Blotato. Expected cost is **$15 to $40/mo**. **[unverified; I will confirm current prices and that each one supports TikTok direct post publicly before recommending a specific vendor]**

**What if:** If the vendor raises prices, shuts down or gets an account flagged, our adapter interface means only one file changes, and we fall back to manual posting from the approval queue (the system packages each post for you to upload by hand). After 2 to 3 months of history we can apply for our own TikTok and YouTube audits if the savings justify it.

### 3.4 Multi-account network: where the line is

| Account type | Allowed? | Rule |
|---|---|---|
| Brand account | Yes | — |
| Founder account | Yes | Disclose your ownership naturally ("I run ONEWRLD"). |
| Gym partner accounts | Yes. They post content packs to their own audience. | Gyms are paid partners (rev share or free shirts), so posts need a **paid-partnership label** and "#ad" or "partner" wording under FTC rules. |
| Affiliates | Yes | Every affiliate post must disclose the commission ("I earn from this link"). The packs ship with the disclosure pre-written. |
| Niche theme pages (gym discipline, Staten Island) | **Only if openly ONEWRLD-run**, for example "a ONEWRLD page" in the bio. | Pages that hide who runs them and funnel to your store cross into Meta's *inauthentic behavior* policy and the FTC's undisclosed material-connection rules. That is a ban risk, not just a reach risk. Recommend at most 1 to 2, and not before month 3. |
| Never | — | Purchased followers or engagement, engagement pods run by bots, accounts made to evade a ban, impersonation, browser-bot posting, scraping. |

### 3.5 Compliance built into the pipeline

- **FTC:** an automatic disclosure check on every affiliate, gym and partner post. The publish queue blocks posts that lack one.
- **Music:** each asset records its audio source (original, licensed with a license ID, or "in-app sound added manually"). Unknown audio is blocked.
- **AI disclosure:** any asset with AI-generated video or voice gets each platform's AI label flag. **[the per-platform API flags are unverified; I'll check each one]**
- **Ad policies:** a pre-flight checklist per platform (no before/after body claims, no "guaranteed results").
- **Privacy:** cookie consent on landing pages (Shopify's native consent banner), and SMS and email opt-in proof stored with a timestamp. SMS also falls under TCPA, so it needs explicit opt-in.
- **UGC:** a written permission record (date, scope, platforms, paid-ads yes/no) is required before any customer video enters the pipeline.

### 3.6 Conversion tracking

- **Meta:** Shopify's native Facebook & Instagram channel sends Pixel plus Conversions API events when data sharing is set to *Maximum*. **[verified via guides]** We use that rather than building our own. We also check that no old duplicate pixel is double-counting.
- **TikTok:** Shopify's TikTok channel installs the pixel. **[unverified]** whether it also sends server-side Events API data natively. I'll check before Phase 4 and fill any gap ourselves.

---

## 4. Build plan

Times assume about 1 to 2 hours of your attention per session. My build time is separate.

| Phase | Goal | Definition of done | Test you run | Your time | New cost/mo | Main risk |
|---|---|---|---|---|---|---|
| **1 Foundation** (M1, M10 basics) | A skeleton that runs safely | Repo, `.env` template, Supabase schema (core tables), job queue, logging, `dry-run` on by default, `kill` command, `health` command | `make health` shows all green; `make kill` then a job attempt is refused and logged; `make test` passes | 2 to 3 h | $0 | Setup friction on your machine |
| **2 Brand Brain** (M2) | Captions that sound like you | Brand bible as YAML, banned-phrase list, hook library (100+), scorer, generator with self-critique pass, feedback capture | Generate 10 captions; you approve or reject each; rejections and reasons are stored; the next batch measurably shifts | 2 h | $5 to $15 (Claude API) | Voice takes iterations to land |
| **3 Video Studio** (M4) | Pro-quality auto edits | 9:16 export, word-level animated captions plus `.srt`, silence trim, loudness normalization, hook-first restructure, end card, quality gate | `make render-test FILE=clip.mp4` gives a branded export plus 3 variants plus a QC report | 2 h | $0 (local transcription) | Render speed on your machine |
| **3.5 Manual posting kit** *(added)* | Start publishing and learning now | Each approved render gets a folder: video, caption, tracked link, posting checklist | You post 1/day manually for 2 weeks | 10 min/day | $0 | — |
| **4 Attribution** (M6) | Sales trace to posts | Shopify read sync, tracked short links (`go.onewrld.com/x`), UTM rules, order-to-post matching, discount-code and affiliate mapping, unit-economics table | Click a test link, place a real test order (refund it after), and see it attributed to that post | 2 h | $0 | Small order volume means attribution is sparse |
| **4B Volume Engine** (M3B) | 1 source becomes 40+ distinct pieces | Atomizer, segment scoring, format templates (30+), similarity filter (perceptual hash plus text embeddings), shoot-day shot list, gym and affiliate packs | Feed one 10-min video and get 40+ quality-gated pieces plus a similarity report showing no near-duplicates | 3 h plus 1 shoot day | $5 to $15 (more API calls) | Quality vs quantity: the gate must be strict |
| **5 Distribution** (M5) | Automated posting with approvals | Adapter interface, unified-layer adapter, Meta direct adapter, scheduler, idempotency keys, retries, dead-letter queue, approval inbox | One platform runs end to end for 1 week in approval mode with zero double posts; then add one platform at a time | 2 h plus daily approvals (about 10 min) | $15 to $40 (posting layer) plus $5 to $8 (small server) | Vendor reliability, platform flags |
| **6 Learning Loop and Dashboard** (M8, M9) | The system gets smarter | Experiment log, weekly post-mortem, Monday memo, `LESSONS.md` auto-proposals (you approve), minimum-sample rules, dashboard pages | Monday memo arrives with real numbers and confidence levels | 2 h | $0 | Too little data early. The memo will say so honestly. |
| **7 Paid Ads** (M7) | Amplify proven winners | Winner detector, contribution-margin ROAS, budget governor with hard caps, recommend-only rules engine, spend alerts | Run a $5/day test on 1 proven post; every recommendation includes a why and a what-if; caps can't be exceeded (tested) | 2 h | Ad spend only, which you set | Budget too small for platform optimization (see Risk 3) |
| **8 Hardening** | Survivable without me | Failure-injection tests, backups, runbook, recovery drill | You run the recovery drill yourself from `RUNBOOK.md` | 2 h | $0 | — |

**Realistic calendar:** Phases 1 to 3 take 1 to 2 weeks. Phases 4 to 5 take 2 to 3 weeks (partly waiting on approvals). Phase 6 runs about 4 weeks in, and the learning loop needs about 6 to 8 weeks of data to say anything real. Phase 7 starts around week 6 to 8.

**Running cost at full operation:** about $40 to $80/mo before ad spend, broken down below.

### Recommended stack (Decision / Why / What if)

| Decision | Why | What if |
|---|---|---|
| **Python 3.12** for all workers | Best ecosystem for video, transcription, statistics and AI. Readable for a beginner. | Very unlikely to need changing. The dashboard can use a different language. |
| **ffmpeg** for every render | Industry-standard, free, scriptable, and gives exact control over captions, crops and loudness | For a single shot that needs pro finishing, you still edit by hand in CapCut. The system accepts finished files as input too. |
| **faster-whisper (local)** with word-level timestamps for transcription | Free, private, accurate enough for burned-in captions | If your machine is too slow or accuracy is poor, switch to a hosted API (about $0.005 to $0.02/min **[unverified]**). That is one config line. |
| **Claude API** for captions, hooks and scoring (a larger model for writing, a small model for scoring) | Strong voice control and self-critique at low cost per caption | A hard monthly spend limit is set in the Anthropic console. If the cap is hit, generation pauses; rendering and posting continue. |
| **New Supabase project (Postgres)** as the system of record | Free tier, you already know it, real Postgres. A separate project keeps a bug here away from your partner portal. | Free projects pause after about a week of inactivity **[verify]**; our scheduler pings it daily. If we outgrow it, Pro is $25/mo. The plain-Postgres schema moves anywhere. |
| **Cloudflare R2** for video files (not Supabase storage) | Video is big. R2 has a free tier and no download fees; Supabase free storage is small. | Fallback: local disk plus Google Drive backup. |
| **Postgres-backed job queue (Procrastinate library)** | No extra service (no Redis). Jobs, retries and schedules live in the same database you can inspect. Restart-safe. | If it ever bottlenecks (it won't at our scale), move to a dedicated queue. Jobs are plain functions, so they port easily. |
| **Docker Compose** | Same setup on your computer and on the server. One command starts everything. | If Docker is painful on your machine, use a plain Python virtual environment, with documented steps for both. |
| **Run location:** your computer through Phase 4; then a **$5 to $8/mo VPS** (Hetzner or similar) for the always-on scheduler and poster. Renders stay on your machine unless it's too slow. | Cheapest reliable setup. Posting needs to be always on; rendering doesn't. | If renders are too slow locally, use the VPS (about $15/mo for a bigger one) or batch them in GitHub Actions. |
| **Dashboard: Monday memo email first, then a small Next.js app on Netlify** that reads Supabase with login | You already have Netlify. The memo is what you'll actually read; dashboard pages come once there's real data. | Interim: Supabase's built-in table viewer. |
| **Tracked links on your own subdomain** (redirects logged by our service) | Free, brand-safe, you own the click data | Fallback: Shopify's native UTM reports only. |
| **pytest, with `make test` running everything** | One command, as required | — |

**Monthly paid dependencies (for your approval when we reach each one):**

| Item | Phase | Est. $/mo |
|---|---|---|
| Claude API | 2+ | $5 to $25 (hard capped) |
| Posting layer | 5 | $15 to $40 [price to verify] |
| VPS | 5 | $5 to $8 |
| X API | 5 | $1 to $5 |
| R2 storage | 3+ | $0 to $3 |
| Licensed music library (optional) | 3+ | about $10 to $20 [unverified] |
| **Total** | | **about $40 to $100** |

---

## 5. Top 5 risks and mitigations

1. **Volume triggers originality penalties and the brand account loses reach.** *Mitigation:* per-account daily caps (start at 1/day per account per platform), footage-level dedup, variants used for testing rather than flooding, and an account-health monitor that freezes posting to any account whose reach drops sharply. Volume ramps only while reach per post holds.
2. **Raw footage starves the system** (your time is the real limit, not compute). *Mitigation:* the shoot-day protocol with a generated shot list, gym and affiliate UGC as a second supply line, and the capacity math report showing exactly how much footage each output target needs.
3. **The $1,000 budget is too small for ad platforms to optimize on purchases.** Meta's learning phase wants about 50 conversions per ad set per week; at $40 to $45 AOV and $5 to $10/day we'll get a few. *Mitigation:* use paid money to amplify proven organic posts (Spark Ads, partnership ads) and for cheap retargeting of warm audiences (video viewers, site visitors); judge results on contribution margin; spend in drop windows only; ad recommendations stay recommend-only in v1.
4. **Platform approvals and API changes** (TikTok, YouTube and Pinterest audits; vendor changes). *Mitigation:* unified layer, adapter interface, manual-post fallback for every platform, circuit breakers, and a dated `PLATFORM_FACTS.md` that's re-checked monthly.
5. **The system becomes too complex for you to own.** The brief describes about 10 enterprise modules. *Mitigation:* ship the smallest useful version of each module first, give every module a README with a one-paragraph definition, have one command per task, write the runbook for a beginner, and require your sign-off at each gate.

Honorable mention: **sparse attribution.** With a few orders a week, per-post revenue is mostly noise. The learning loop will use clicks and add-to-carts as leading indicators and pool evidence across similar posts, and it will say when it doesn't know.

---

## 6. Where the brief is weak, and what I'd do instead

1. **"Maximum volume" is the wrong objective.** Optimize *distinct, quality-gated pieces per hour of raw footage* and *revenue per post*. 25+/day is achievable only as a network total (for example 5 accounts × 5 platforms × 1/day), never as 25/day on one account. Ramp only while reach per post holds.
2. **The remix matrix as a publishing engine.** Overlay and crop permutations of the same footage read as duplicates to platform fingerprinting. Use it to generate and test candidates, then publish few. Spend the differentiation effort on *new segments*.
3. **Hidden-ownership niche pages.** These must be openly ONEWRLD-run or not exist. Otherwise you risk a ban plus FTC trouble.
4. **Attribution comes too late (Phase 4).** Tracked links are cheap and every post from day one should carry one. I fold the link generator into Phase 3.5 so the first manual posts are already measurable.
5. **Distribution waits until Phase 5.** I added Phase 3.5 so you start posting manually within 2 weeks. The learning clock starts when posts go live, not when automation is finished.
6. **Trending audio through the API.** It generally can't be done (see 3.1). Plan for a hybrid: auto-publish evergreen content with original or licensed audio, and hand off trend pieces to your phone for a 30-second finish.
7. **Autonomous ad mode.** At this budget the downside of an automated mistake outweighs the time saved. Keep v1 recommend-only. Revisit autonomy at a $3,000+/mo spend with 90 days of history.
8. **Thompson sampling early on.** It's the right tool, but with tiny samples it mostly reflects the prior. I'll build it in Phase 6 with sensible priors and minimum-sample gates, and the memo will show how much confidence it actually has.
9. **Full custom dashboard (M9) as a major build.** The Monday memo plus an approvals inbox gives you 80% of the value. Dashboard pages get added once real data exists to fill them.
10. **Enlistly integration is assumed.** I don't know whether it has an API. If it doesn't, affiliate packs go out by email or shared-folder link with each affiliate's code pre-filled from a CSV export. That works fine.
11. **Snapchat.** Drop it from v1. No open posting path, and low return for this audience.

---

## Corrections from owner

**C-001 (2026-11-01): Own drops are the main product line. Gym collabs are secondary.**

What changes in the design:

- **Content calendar:** built around ONEWRLD's own drop cycle (tease, reveal, drop day, restock or last call, sold out). Gym collab launches slot in as separate events.
- **Content pillars:** reweighted. Own-drop product detail, drop countdowns, founder story and community proof are primary. Gym culture stays the backdrop and identity. Collab reveals and event recaps become one format among many.
- **Volume Engine supply:** product and lookbook shoots for own drops become a main source on shoot day, alongside talks and gym sessions.
- **Distribution weight:** the brand and founder accounts carry most of the volume. Gym partner packs become a secondary supply line, used only around collab launches.
- **Affiliates:** more important now. Affiliates promoting own drops are a steady channel; gyms only help around their own collab.
- **Attribution and margin:** tracked separately for own-drop SKUs and collab SKUs (costs, prices and rev-share differ).
- **Ads:** paid testing focuses on own drops first, because ONEWRLD keeps the full margin with no partner split. **[assumption: confirm whether collabs have a rev share]**

**C-002 (2026-11-01): Owner answers to the Phase 1 items**

- **Computer:** a capable Windows PC. Plan: run everything locally, using Docker Desktop with WSL2. Rendering happens on the PC.
- **GitHub:** has an account. Supabase: has an account; a new, separate project will be created for this system.
- **Alert email:** stored as a plain setting in the config file (not a secret).
- **Platforms in use:** Instagram, TikTok, X, YouTube and Facebook. Instagram and Facebook are linked.
- **v1 adapter scope:** Instagram and Facebook direct through Meta, TikTok and YouTube through the posting layer, X direct (pay-per-use). Pinterest and Threads are deferred: optional later, low effort.
- **Product mix:** about 75% of drops are ONEWRLD-only collections (for example *Fall of Icarus*). Gyms are used for leverage only (reach and events), not as the core line.
- **Still open:** platform handles; whether Instagram is a Business or Creator account.

## Decisions to log in `DECISIONS.md` once Phase 1 starts

D-001 Unified posting layer for TikTok, YouTube and Pinterest · D-002 Separate Supabase project · D-003 Postgres job queue · D-004 Local transcription · D-005 R2 for video · D-006 Recommend-only ads in v1 · D-007 Openly-owned accounts only · D-008 Variants for testing, not flooding · D-009 Phase 3.5 manual posting kit · D-010 Tracked links from the first post.

---

## Sources (checked 2026-11-01)

- TikTok Content Posting API, Direct Post reference: https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- Postiz TikTok provider notes: https://docs.postiz.com/self-host/providers/tiktok
- TikTok audit timing (third-party): https://bundle.social/blog/tiktok-api-approval
- Instagram content publishing: https://developers.facebook.com/docs/instagram-platform/content-publishing
- IG publishing limit endpoint: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit
- Instagram originality update (Apr 2026): https://tubefilter.com/2026/04/30/instagram-removes-algorithm-recommendations-repost-content-aggregator
- Instagram creators blog: https://creators.instagram.com/blog/rewarding-original-creators-on-instagram
- YouTube monetization / inauthentic content: https://support.google.com/youtube/answer/1311392
- YouTube upload private restriction (third-party): https://postproxy.dev/blog/automate-youtube-uploads/
- X pay-per-use: https://opentermsarchive.org/en/memos/x-replaces-its-dollar200-entry-level-api-plan-with-a-pay-per-use-model/
- Pinterest access tiers: https://developers.pinterest.com/docs/key-concepts/access-tiers/
- Ayrshare pricing (third-party): https://www.blotato.com/blog/ayrshare-pricing
- Meta CAPI on Shopify (third-party): https://stormy.ai/blog/meta-pixel-conversions-api-shopify-tutorial-2026
