"""Shot list: builds a shoot day from the format library (brand/formats.toml).

Picks the highest-value formats for what's in stock, fits them into your time budget,
orders them by location so you film everything at home, then outside, then at the gym,
and suggests opening lines (hooks) for each. Output is a checklist you can follow on
your phone.

Name your clips starting with the format code (e.g. "F06_1.mp4") and the system
records which format each video used, so it can learn which formats sell. Optional.
"""

from __future__ import annotations

import tomllib
from datetime import date
from functools import lru_cache
from pathlib import Path

from onewrld import products
from onewrld.brand import BRAND_DIR

# Which product handle each format `products` value needs in stock.
NEEDS = {
    "hoodie": ["onewrld-fall-of-icarus-zip-hoodie"],
    "sweats": ["onewrld-fall-of-icarus-sweatpants"],
    "set": ["onewrld-fall-of-icarus-zip-hoodie", "onewrld-fall-of-icarus-sweatpants"],
    "hat": ["onewrld-acid-wash-signature-hat"],
    "cup": ["onewrld-shaker-cup"],
}
HOOK_PRODUCT = {"hoodie": "onewrld-fall-of-icarus-zip-hoodie",
                "sweats": "onewrld-fall-of-icarus-sweatpants", "set": "collection:fall_of_icarus",
                "hat": "onewrld-acid-wash-signature-hat", "cup": "onewrld-shaker-cup"}

# Order of value right now: sell the Fall of Icarus stock and build the story (owner's goal,
# 2026-11-02). Talking clips first: one talk becomes many posts (Volume Engine).
PRIORITY = ["F02", "F01", "F06", "F08", "F04", "F09", "F11", "F12", "F14", "F07", "F10",
            "F16", "F13", "F18", "F03", "F17", "F15", "F30", "F21", "F22", "F05", "F32",
            "F19", "F29", "F31", "F20", "F25", "F27"]
LOCATION_ORDER = {"home": 0, "anywhere": 0, "outdoor": 1, "gym": 2}
SWITCH_MINUTES = 15   # travel / setup time each time the location changes


@lru_cache(maxsize=2)
def _load(name: str, mtime: float) -> dict:
    return tomllib.loads((BRAND_DIR / name).read_text(encoding="utf-8"))


def formats() -> list[dict]:
    path = BRAND_DIR / "formats.toml"
    return _load("formats.toml", path.stat().st_mtime)["formats"]


def hooks_library() -> list[dict]:
    path = BRAND_DIR / "hooks.toml"
    return _load("hooks.toml", path.stat().st_mtime)["hooks"]


def _in_stock(fmt: dict, stock: set[str]) -> bool:
    return all(h in stock for h in NEEDS.get(fmt["products"], []))


def plan(minutes: int = 120, stock: set[str] | None = None, include_drop: bool = False) -> list[dict]:
    """Formats to film, in filming order, within `minutes` (including location changes)."""
    stock = stock if stock is not None else {p["handle"] for p in products.catalog()}
    by_id = {f["id"]: f for f in formats()}
    eligible = [by_id[i] for i in PRIORITY if i in by_id]
    eligible += [f for f in formats() if f["id"] not in PRIORITY]
    chosen: list[dict] = []
    for f in eligible:
        if f["film_minutes"] <= 0 or (f["drop_only"] and not include_drop) or not _in_stock(f, stock):
            continue
        trial = chosen + [f]
        if _total_minutes(trial) <= minutes:
            chosen = trial
    return sorted(chosen, key=lambda f: (LOCATION_ORDER.get(f["location"], 0),
                                         PRIORITY.index(f["id"]) if f["id"] in PRIORITY else 99))


def _total_minutes(fmts: list[dict]) -> int:
    locations = {LOCATION_ORDER.get(f["location"], 0) for f in fmts}
    return sum(f["film_minutes"] for f in fmts) + SWITCH_MINUTES * max(0, len(locations) - 1)


def suggested_hooks(fmt: dict, n: int = 2, exclude: set[str] | None = None) -> list[str]:
    """Hooks for this format. Product formats get hooks about THAT product (or its collection);
    brand formats get brand-wide hooks of the format's types. Never repeats a hook already
    suggested for another format on the same list."""
    exclude = exclude or set()
    target = HOOK_PRODUCT.get(fmt["products"])
    if target:
        allowed = {target}
        if target.startswith("onewrld-fall-of-icarus") or target.startswith("collection:fall"):
            allowed.add("collection:fall_of_icarus")
    else:
        allowed = {"brand"}
    lib = [h for h in hooks_library() if h.get("product") in allowed and h["text"] not in exclude]
    preferred = [h for h in lib if h["type"] in fmt["hook_types"]]
    picks: list[str] = []
    for t in fmt["hook_types"]:            # one from each of the format's hook types first
        for h in preferred:
            if h["type"] == t and h["text"] not in picks:
                picks.append(h["text"])
                break
    for h in preferred + lib:              # then any fitting hook for this product
        if len(picks) >= n:
            break
        if h["text"] not in picks:
            picks.append(h["text"])
    return picks[:n]


def render_text(chosen: list[dict], day: date, minutes: int) -> str:
    names = {0: "AT HOME", 1: "OUTSIDE", 2: "AT THE GYM"}
    talking = sum(1 for f in chosen if f["talking"])
    est_posts = len(chosen) * 4
    lines = [f"ONEWRLD SHOOT DAY: {day:%A %B %d}",
             f"{len(chosen)} formats, about {_total_minutes(chosen)} of your {minutes} minutes.",
             f"Expected output: about {est_posts}+ finished videos "
             f"({talking} talking clip(s) can be cut into many more).", "",
             "Before you start: phone vertical, lens wiped, quiet room, no music playing.",
             "Hold every shot 2 seconds longer than feels natural.",
             "Name clips starting with the code (e.g. F06_1.mp4) if you can: optional, helps the system learn.",
             ""]
    current = None
    used: set[str] = set()
    for f in chosen:
        loc = LOCATION_ORDER.get(f["location"], 0)
        if loc != current:
            current = loc
            lines += ["=" * 60, names[loc], "=" * 60]
        tag = " (talking)" if f["talking"] else ""
        lines += ["", f"[ ] {f['id']}  {f['name']}{tag}  ~{f['film_minutes']} min",
                  f"    {f['what']}"]
        for shot in f["shots"]:
            lines.append(f"    [ ] {shot}")
        if f.get("edit"):
            lines.append(f"    edit: {f['edit']}")
        hooks = suggested_hooks(f, exclude=used)
        used.update(hooks)
        if hooks:
            lines.append("    opening line ideas: " + " / ".join(f'"{h}"' for h in hooks))
    lines += ["", "After the shoot: copy the clips into media\\inbox, then run:",
              "    python -m onewrld batch", "    (talking clips: python -m onewrld render <clip> --talk)"]
    return "\n".join(lines) + "\n"


def write(root: Path, minutes: int, day: date, include_drop: bool = False) -> Path:
    chosen = plan(minutes, include_drop=include_drop)
    out = root / "media" / "shotlists" / f"shotlist_{day.isoformat()}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_text(chosen, day, minutes), encoding="utf-8")
    return out
