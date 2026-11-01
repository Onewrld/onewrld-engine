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
