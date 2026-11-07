"""Config: reads settings from `.env` and environment variables into one object.

Every other module asks this file for settings instead of reading `.env` itself,
so there is exactly one place where settings are defined and checked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

VALID_MODES = ("dry_run", "staging", "live")

# Project root = the folder that contains pyproject.toml.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    """A setting is missing or invalid. The message says which one and how to fix it."""


@dataclass(frozen=True)
class Settings:
    mode: str
    alert_email: str
    # repr=False: secrets are never shown if settings get printed or logged.
    database_url: str = field(repr=False)  # empty string = not configured yet
    db_schema: str  # the Postgres schema (folder of tables) this system uses
    root: Path
    # Email sending (Gmail with an app password by default). Empty = not configured.
    smtp_user: str = ""
    smtp_app_password: str = field(default="", repr=False)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    # Supabase project URL + service_role key: lets `portal invite` create logins. The key is
    # SECRET (it bypasses all security rules): .env only, never in the website or git.
    supabase_url: str = ""
    supabase_service_key: str = field(default="", repr=False)
    # High-volume portal (D-067): most versions made per upload (one per affiliate, 3 to 10),
    # and the portal's web address for "posts waiting" emails.
    portal_max_versions: int = 6
    portal_url: str = ""

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_user and self.smtp_app_password and "@" in self.alert_email)

    @property
    def state_dir(self) -> Path:
        """Folder for runtime flags such as the kill switch. Never committed."""
        return self.root / "state"

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


def load_settings(root: Path | None = None, env_file: Path | None = None) -> Settings:
    """Load and validate settings. Raises ConfigError with a plain-English fix."""
    root = root or Path(os.environ.get("ONEWRLD_ROOT", PROJECT_ROOT))
    env_file = env_file or root / ".env"
    # override=False: a real environment variable beats the .env file.
    load_dotenv(env_file, override=False)

    mode = os.environ.get("MODE", "dry_run").strip().lower() or "dry_run"
    if mode not in VALID_MODES:
        raise ConfigError(
            f"MODE='{mode}' is not valid. Use one of: {', '.join(VALID_MODES)}. "
            "Fix it in your .env file."
        )

    return Settings(
        mode=mode,
        alert_email=os.environ.get("ALERT_EMAIL", "").strip(),
        database_url=os.environ.get("DATABASE_URL", "").strip(),
        db_schema=os.environ.get("DB_SCHEMA", "engine").strip() or "engine",
        root=root,
        smtp_user=os.environ.get("SMTP_USER", "").strip(),
        # Google shows app passwords in groups of 4 with spaces; spaces are removed.
        smtp_app_password=os.environ.get("SMTP_APP_PASSWORD", "").replace(" ", "").strip(),
        smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com",
        smtp_port=_int_setting("SMTP_PORT", 465),
        supabase_url=os.environ.get("SUPABASE_URL", "").strip().rstrip("/"),
        supabase_service_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        portal_max_versions=max(3, min(10, _int_setting("PORTAL_MAX_VERSIONS", 6))),
        portal_url=os.environ.get("PORTAL_URL", "").strip(),
    )


def _int_setting(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name}='{raw}' must be a whole number. Fix it in your .env file.")
