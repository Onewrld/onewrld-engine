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
