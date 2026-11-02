"""Brand Brain scorer: checks a caption against brand/brand_bible.yaml. Free; no AI.

score_caption() returns a score 0-100, whether it is BLOCKED, and the reasons.
- Blocked (score 0): contains a banned phrase. It can never be used, regardless of score.
- Otherwise: starts at 100 and loses points for each soft rule it breaks.
QUALITY_FLOOR is the minimum score a caption needs to be offered for approval at all.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from onewrld.config import PROJECT_ROOT

BRAND_DIR = PROJECT_ROOT / "brand"
QUALITY_FLOOR = 70


@dataclass
class Score:
    score: int
    blocked: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def passes(self) -> bool:
        return not self.blocked and self.score >= QUALITY_FLOOR


@lru_cache(maxsize=4)
def _load_bible(path: str, mtime: float) -> dict:
    # mtime in the cache key: editing the YAML takes effect without restarting.
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_bible(path: Path | None = None) -> dict:
    path = path or BRAND_DIR / "brand_bible.yaml"
    return _load_bible(str(path), path.stat().st_mtime)


def _is_emoji(ch: str) -> bool:
    return unicodedata.category(ch) == "So" or 0x1F000 <= ord(ch) <= 0x1FAFF


def _phrase_pattern(phrase: str) -> re.Pattern:
    """Match whole words only, so 'goat' doesn't hit 'goatee'."""
    p = re.escape(phrase.lower())
    if phrase[:1].isalnum():
        p = r"\b" + p
    if phrase[-1:].isalnum():
        p = p + r"\b"
    return re.compile(p)


def score_caption(text: str, bible: dict | None = None) -> Score:
    bible = bible or load_bible()
    rules = bible["rules"]
    reasons: list[str] = []
    low = text.lower().replace("’", "'")

    banned = [p for p in bible["banned_phrases"] if _phrase_pattern(str(p)).search(low)]
    if banned:
        return Score(0, True, [f"banned phrase: '{b}'" for b in banned])

    score = 100
    if not text.strip():
        return Score(0, True, ["empty caption"])

    excl = text.count("!")
    if excl > rules["max_exclamation_marks"]:
        score -= 15
        reasons.append(f"{excl} exclamation marks (max {rules['max_exclamation_marks']})")
    if "!!" in text or "??" in text:
        score -= 10
        reasons.append("repeated punctuation reads as shouting")

    emojis = sum(1 for ch in text if _is_emoji(ch))
    if emojis > rules["max_emojis"]:
        score -= 10 * (emojis - rules["max_emojis"])
        reasons.append(f"{emojis} emojis (max {rules['max_emojis']})")

    tags = len(re.findall(r"(?<!\w)#\w+", text))
    if tags > rules["max_hashtags"]:
        score -= 10
        reasons.append(f"{tags} hashtags (max {rules['max_hashtags']})")

    allowed = {w.upper() for w in rules["caps_allowed"]}
    shouting = [w for w in re.findall(r"\b[A-Z0-9]{3,}\b", text)
                if w not in allowed and not w.isdigit()]
    if shouting:
        score -= 10
        reasons.append(f"all-caps words: {', '.join(shouting)}")

    n = len(text)
    if n > rules["soft_max_chars"]:
        score -= 15
        reasons.append(f"{n} characters (soft max {rules['soft_max_chars']})")
    elif n > rules["ideal_max_chars"]:
        score -= 5
        reasons.append(f"{n} characters (ideal under {rules['ideal_max_chars']})")

    if text.strip().endswith("?") and text.count(".") == 0:
        score -= 5
        reasons.append("question hook (voice prefers statements)")

    return Score(max(score, 0), False, reasons)
