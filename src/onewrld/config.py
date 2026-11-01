"""Config: reads settings from `.env` and environment variables into one object.

Every other module asks this file for settings instead of reading `.env` itself,
so there is exactly one place where settings are defined and checked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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
    database_url: str  # empty string = not configured yet
    root: Path

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
        root=root,
    )
