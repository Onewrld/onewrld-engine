# RUNBOOK.md: how to run, stop and recover the system (Windows)

Type the commands below into **PowerShell**, from inside the `onewrld` folder.

## 0. One-time install
1. Install **Python 3.12+** from python.org. On the first installer screen, tick **"Add python.exe to PATH"**.
2. Install **Git** from git-scm.com (all default options).
3. Install **ffmpeg** (the video tool, needed from Phase 3):
   ```
   winget install Gyan.FFmpeg
   ```
4. Download the code (replace the URL with your repo):
   ```
   git clone https://github.com/YOUR_USERNAME/onewrld-engine.git onewrld
   cd onewrld
   ```
5. Create the virtual environment (a private folder of Python packages just for this project) and install:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e ".[dev]"
   ```
   If PowerShell blocks `activate`, run this once, then try again:
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
6. Create your settings file:
   ```
   copy .env.example .env
   notepad .env
   ```
   Set `ALERT_EMAIL`. Leave `MODE=dry_run`.

## 1. Every time you open a new PowerShell window
```
cd onewrld
.venv\Scripts\activate
```
You'll see `(.venv)` at the start of the line. That means it's active.

## 2. Daily commands
| Command | What it does |
|---|---|
| `python -m onewrld health` | Checks everything. `[FAIL]` = must fix, `[WARN]` = works but look at it. |
| `python -m onewrld status` | One line: mode and kill switch. |
| `python -m onewrld test` | Runs every automated test. All must pass. |

## 3. EMERGENCY STOP
```
python -m onewrld kill "why you are stopping"
```
This blocks all posting and spending immediately, in every mode. It works even if the internet or database is down.

To turn it back off (a reason is required):
```
python -m onewrld resume "why it is safe now"
```

## 4. Where to look when something is wrong
- `logs/onewrld.jsonl`: every event, one per line. The newest entries are at the bottom.
- Run `python -m onewrld health` first. It tells you what is wrong in plain words.

## 5. Updating to the latest code
```
git pull
pip install -e ".[dev]"
python -m onewrld test
```
If any test fails after an update, run `kill` first, then tell Claude what the output said.

## 6. Connecting your Supabase database (one time)
1. Open your **onewrld-engine** project at supabase.com/dashboard.
2. Click the **Connect** button at the top of the page.
3. Find the **Session pooler** connection string and copy the URI. It looks like:
   `postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres`
   Use **Session pooler**, not "Direct connection". Direct connection needs IPv6, which many home internet connections don't have.
4. Open your settings: `notepad .env`
5. Paste the URI after `DATABASE_URL=`, then replace `[YOUR-PASSWORD]` (including the brackets) with your database password. Save.
6. Create the tables:
   ```
   python -m onewrld migrate
   ```
7. Check:
   ```
   python -m onewrld health
   ```
   You want `[ OK ] database  connected, schema 'engine' up to date`.

Never paste the `.env` contents or the connection string to anyone, Claude included.
If you think the password leaked: Supabase → Project Settings → Database → **Reset database password**, then update `.env`.

## 7. The job queue
| Command | What it does |
|---|---|
| `python -m onewrld jobs` | Shows queued, running, done and dead jobs, plus the latest 10. |
| `python -m onewrld worker` | Runs waiting jobs. Stops by itself after 25 jobs or 5 minutes. |
| `python -m onewrld alerts` | Shows problems you haven't looked at yet. |
| `python -m onewrld ack 12` | Marks alert #12 as seen. |

A **dead** job means the system gave up on it and raised an alert. Nothing is lost; it stays in the table with its error message (`last_error`) for you or Claude to inspect.

## 8a. If health says "old tables found in 'public'"
That's a one-time leftover from bug M-004. Run:
```
python -m onewrld repair-schema --yes
```
It removes only ONEWRLD's own tables from the wrong place and recreates them correctly. Only Phase 1 demo data is affected.

## 8. If the kill switch says ON and you didn't turn it on
- "database tables not created yet": run `python -m onewrld migrate`.
- "failing safe": the system can't reach the database, so it refuses to act. Check your internet, then run `python -m onewrld health`.
This is deliberate. When the system is unsure, it stops instead of posting.

## 9. Setting up email alerts (one time, about 5 minutes)
The system sends alerts from your Gmail account to itself, using a Google **app password**: a separate 16-letter password for one app. You can revoke it any time, and your real password is never stored.

1. Go to **myaccount.google.com** → **Security**. Make sure **2-Step Verification** is ON (Google requires it for app passwords).
2. Go to **myaccount.google.com/apppasswords**.
3. Name it `onewrld-engine`, click **Create**, and copy the 16 letters.
4. Add your email settings with this one paste in PowerShell (from the `onewrld` folder). Replace `PASTE16LETTERS` with the app password first:
   ```
   Add-Content -Path .env -Value @("SMTP_USER=adammekkawiac@gmail.com", "SMTP_APP_PASSWORD=PASTE16LETTERS")
   ```
5. Test it:
   ```
   python -m onewrld test-email
   ```
   Check your inbox, and your spam folder. If it's in spam, mark it "Not spam" so real alerts don't get missed.

**How alerts behave:** only warnings and critical problems are emailed. They're bundled into one email, at most 4 per hour and 20 per day. Alerts held back by the cap go out in the next email; none are lost.
**If the app password leaks:** delete it at myaccount.google.com/apppasswords, create a new one, and update `.env`.

## 10. Phase 1 acceptance check
```
python -m onewrld phase1-check
```
This runs health, all tests, a kill-switch drill, a demo job and a test email. Every line should say `[PASS]` and the last line `Phase 1: ACCEPTED`.

## 11. When something fails
```
python -m onewrld diagnose
```
This prints a report and saves it to `diagnose.txt`. It never includes passwords or keys, so it's safe to paste to Claude in full.

## 12. Brand Brain: voice quiz and captions
First time only:
```
python -m onewrld migrate
python -m onewrld captions import
```
Then:
| Command | What it does |
|---|---|
| `python -m onewrld quiz` | 15 this-or-that pairs. Type `a`, `b`, `both` or `n` (neither). `q` stops; your answers so far are kept. |
| `python -m onewrld voice` | Shows the voice profile your quiz answers produced. |
| `python -m onewrld captions review` | Shows waiting captions one at a time: `a` approve, `r` reject (then type why), `e` edit (type your version), `s` skip, `q` quit. |
| `python -m onewrld captions list` | Every caption with its score and status. |
| `python -m onewrld captions feedback` | Your decisions, reasons and quiz profile in one paste-safe report. |
| `python -m onewrld captions score "text"` | Checks any caption you write against the brand rules. |

The rules live in `brand/brand_bible.toml`. To ban a phrase, add it to `banned_phrases` and save; it takes effect immediately.

## 13. Video Studio
Needs ffmpeg (section 0, step 3). Check with `python -m onewrld health`: the ffmpeg line should say OK.

| Command | What it does |
|---|---|
| `python -m onewrld render-test` | Makes a sample clip and renders it 4 ways. Use it to check everything works. |
| `python -m onewrld render "C:\path\to\clip.mp4"` | Renders your clip: main version + 3 variants, each with one of your approved captions, logo, end card, quality-checked. |
| `python -m onewrld render clip.mp4 --caption "your text"` | Same, but with the caption you type. |
| `python -m onewrld render clip.mp4 --variants 5 --seconds 20` | More variants (max 5) or a shorter max length. |
| `python -m onewrld renders` | Lists recent renders and whether each passed the quality check. |

Finished videos go in the `renders` folder inside the project. Open it with: `explorer renders`.
**Tip:** drag a video file onto the PowerShell window to paste its full path.
Rendering takes about 10 to 40 seconds per version, depending on clip length and your PC.

## 14. Speech: word-by-word captions and dead-air cuts (optional)
**Step 1: check your Python version**
```
python --version
```
- **3.11, 3.12, 3.13 or 3.14:** go to step 3.
- **3.15:** the speech model's parts (`onnxruntime`) don't support 3.15 yet. Do step 2 first.

**Step 2 (only if you're on 3.15): add Python 3.13 next to it.** About 10 minutes, one time. Your 3.15 stays installed.
This also moves the project into its own private Python folder (`.venv`), which `health` now checks for (the `environment` line).
```
winget install Python.Python.3.13
```
Close PowerShell, open a new one, go to the project, and rebuild its environment on 3.13:
```
cd onewrld
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m onewrld health
```
Your `.env`, database, captions and renders are untouched; only the project's private Python folder is rebuilt.

**Step 3: install the speech model**
```
pip install -e ".[speech]"
python -m onewrld health
```
The `speech` line should say OK. The first transcription downloads the model (about 480 MB, once).

**Use it**
| Command | What it does |
|---|---|
| `python -m onewrld transcribe "clip.mp4"` | Prints the words it heard, how long it took, and how much is left after cutting pauses. Good first test. |
| `python -m onewrld render "clip.mp4" --talk` | Talking clip: captions follow your words one at a time (current word white, others gray), pauses over 0.6 s are cut, and a `.srt` subtitle file is saved next to each video. |

## 15. Volume Engine: make videos from what you already have
**One time (and whenever products change):**
```
python -m onewrld pull-products
```
This downloads your in-stock product photos into `media\products\`.

**Add your own content:** put any clips or photos you already have (old Reels, gym footage, phone photos) into `media\inbox\`. Open it with: `explorer media\inbox`.
To tag a clip with a product so it gets that product's captions, put it in a subfolder named after the product, e.g. `media\inbox\onewrld-fall-of-icarus-sweatpants\`.

**Make everything:**
```
python -m onewrld batch
```
Every photo and clip becomes a main version + 3 variants, each with a caption you approved **for that product** (sweatpants lines never land on the hat). Then it checks that no two versions look like near-copies.
Re-running is cheap: anything already made is reused; only new files render.

**If it says some files have no approved caption:**
```
python -m onewrld captions import
python -m onewrld captions review
```
Then run `batch` again.

## 16. Posting: schedule, approve, post (Distribution, Phase 5.1)
**Once a week (about 5 minutes):**
```
python -m onewrld schedule
python -m onewrld posts review
```
`schedule` fills the next 7 days: 1 post a day per platform (TikTok, Instagram, YouTube Shorts, Facebook, X), never the same clip twice on one platform in a week, and a different version of a clip on each platform. `posts review` shows each post: `a` approve, `r` reject (say why), `A` approve everything left, `q` stop.

**Each day:**
```
python -m onewrld kit
```
This makes a folder for today, with one subfolder per post in posting order: `video.mp4` plus `caption.txt` (and `title.txt` for YouTube). Upload, paste, then:
```
python -m onewrld posted 12
```
(12 = the post number shown in the kit). Optionally add the post's link: `--url https://...`
`python -m onewrld posts` shows the week at a glance.

**One-time: tracked bio links.** Instagram and TikTok captions can't hold tappable links, so set your profile link to a tracked one, so Shopify knows which app a visitor came from:
- Instagram bio: `https://onewrld.us/?utm_source=instagram&utm_medium=bio`
- TikTok bio: `https://onewrld.us/?utm_source=tiktok&utm_medium=bio`

**Change post times or daily limits:** edit `brand/platforms.toml` (for example `daily_cap = 2`), then run `schedule` again.

## 17. Hooks and shot lists
**Hooks** are the opening line of a video: the first 1 to 2 seconds, on screen. There are 110 in `brand/hooks.toml`, all written to your rules.
```
python -m onewrld captions import
python -m onewrld hooks review
```
Review 20 at a time (`--limit 40` for more): `a` approve, `r` reject with a reason, `e` edit.
Once some are approved, every video you render puts a **different approved hook on each version**. Each clip then automatically tests which opening line works best.

**Shot list for a shoot day:**
```
python -m onewrld shotlist --minutes 120
```
This prints a checklist (and saves it in `media\shotlists\`): which formats to film, in what order (home, then outside, then the gym), every shot, and two opening-line ideas for each.
Optional: name clips starting with their code (`F06_1.mp4`) so the system learns which formats sell.

## 18. Affiliate Portal: setup (database part)
The portal is a private website where affiliates upload clips, you approve the finished posts and pick who gets them, and they post. This section sets up its database and security. The website screens come next.

**One time:**
```
python -m onewrld portal setup
```
**Invite yourself, then create your login in Supabase:**
```
python -m onewrld portal invite you@email.com "Adam"
```
In Supabase: **Authentication → Users → Add user** with that same email. Then:
```
python -m onewrld portal owner you@email.com
```
**Invite an affiliate** (their Enlistly code and link go on every post they get):
```
python -m onewrld portal invite blake@email.com "Blake" --code BLAKE10 --link "https://onewrld.us/?ref=blake"
```
`python -m onewrld portal members` shows everyone. `portal deactivate EMAIL` cuts someone off instantly (they keep nothing new; they see nothing new).

**What the security rules guarantee** (all tested):
- Only invited emails get an account. Anyone else who logs in sees nothing and can upload nothing.
- Affiliates see only their own uploads and the posts sent to them, not each other.
- Only you can approve, reject or assign. Pressing approve twice never sends a post twice.
- Every affiliate caption gets their own link and code, plus the required `#ad` disclosure.
- Uploading requires agreeing that ONEWRLD may edit and repost the clip (recorded with the time).

## 19. Affiliate Portal: put the website live (about 20 minutes, once)
**1. Supabase keys.** Supabase → Project Settings → **API**:
- Send Claude the **Project URL** and the **anon public** key. Both are public by design (every visitor's browser needs them); the database rules protect the data. Claude puts them in `portal/config.js`.
- **Never send the `service_role` key to anyone.** Put it in your `.env` on the PC only:
```
SUPABASE_URL=https://YOUR-PROJECT-REF.supabase.co
SUPABASE_SERVICE_ROLE_KEY=paste-the-service_role-key-here
```
**2. Create the portal tables** (from section 18, if not done): `python -m onewrld portal setup`

**3. Netlify:** Add new site → **Import an existing project** → GitHub → `Onewrld/onewrld-engine`. Netlify reads `netlify.toml` and publishes the `portal` folder; no build settings needed. You get an address like `onewrld-team.netlify.app` (you can rename it in Site settings).

**4. Supabase login settings** (Authentication section; labels may differ slightly):
- **Email** sign-in on.
- **Allow new users to sign up: OFF.** Logins are created only by `portal invite`.
- **URL configuration:** Site URL = your Netlify address; add it to Redirect URLs too.

**5. Invite people** (this now also creates their login):
```
python -m onewrld portal invite you@email.com "Adam"
python -m onewrld portal owner you@email.com
python -m onewrld portal invite blake@email.com "Blake" --code BLAKE10 --link "https://onewrld.us/?ref=blake"
```
They open the Netlify address, type their email, tap the link in their inbox, and they're in.

**Free plan limits:** 50 MB per clip, 1 GB total. After upgrading to Supabase Pro, change `maxUploadMB` in `portal/config.js` (ask Claude) and the limit goes up.

**Note:** the Approve screen stays empty until the next module (your PC turning uploads into finished posts).
