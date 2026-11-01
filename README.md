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
| `src/onewrld/cli.py` | The commands you type. |
| `tests/` | Automated tests. Run them with `python -m onewrld test`. |
