"""Distribution: turn finished videos into a posting schedule across platforms.

Pieces:
- platforms.toml: each platform's daily cap, post times, caption limits, link rules.
- schedule(): fills the next N days. Each platform gets at most `daily_cap` posts a day.
  The same source footage is never posted twice on one platform within ASSET_GAP_DAYS,
  and each platform gets a different variant of a clip where one exists, so no platform
  sees near-copies (D-008, D-031).
- Every post gets a tracked link (UTM tags: labels in the link that tell Shopify which
  post and platform a visitor came from) and platform-shaped caption text.
- Every post starts as "planned" and needs your approval (manual-approval mode is ON).
- The posting kit: approved posts for a day, exported to a folder: video + caption text,
  ready to post by hand. Automatic posting (Phase 5.2) plugs in through adapters.py.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import psycopg

from onewrld import products
from onewrld.brand import BRAND_DIR
from onewrld.config import Settings
from onewrld.logging_setup import get_logger

log = get_logger(__name__)
ASSET_GAP_DAYS = 7          # same footage at most once a week per platform
X_LINK_LENGTH = 23          # X counts every link as 23 characters


@dataclass(frozen=True)
class Platform:
    id: str
    name: str
    handle: str
    daily_cap: int
    post_times: tuple[str, ...]
    link_clickable: bool
    caption_max: int
    hashtags_max: int
    title_max: int | None = None


@lru_cache(maxsize=2)
def _config(mtime: float) -> dict:
    return tomllib.loads((BRAND_DIR / "platforms.toml").read_text(encoding="utf-8"))


def config() -> dict:
    return _config((BRAND_DIR / "platforms.toml").stat().st_mtime)


def platforms() -> list[Platform]:
    out = []
    for p in config()["platforms"]:
        out.append(Platform(p["id"], p["name"], p["handle"], int(p["daily_cap"]),
                            tuple(p["post_times"]), bool(p["link_clickable"]),
                            int(p["caption_max"]), int(p["hashtags_max"]), p.get("title_max")))
    return out


def tz() -> ZoneInfo:
    return ZoneInfo(config()["timezone"])


def product_for_asset(path: str) -> str | None:
    """Product handle from the folder a clip sits in (media/inbox/<handle>/clip.mp4)."""
    handle = Path(path).parent.name
    return handle if products.by_handle(handle) else None


# --- links and captions ---------------------------------------------------------

def tracked_link(product: str | None, platform: str, post_id: int) -> str:
    base = config()["store_url"].rstrip("/")
    p = products.by_handle(product) if product else None
    url = f"{base}/products/{product}" if p else base + "/"
    tags = {"utm_source": platform, "utm_medium": "social",
            "utm_campaign": (p or {}).get("collection", "brand"), "utm_content": f"post{post_id}"}
    return f"{url}?{urlencode(tags)}"


def hashtags(product: str | None, limit: int) -> list[str]:
    tags = [config()["brand_hashtag"]]
    p = products.by_handle(product) if product else None
    if p and p.get("collection") == "fall_of_icarus":
        tags.append("#fallofIcarus")
    return tags[:limit]


def shape_caption(text: str, platform: Platform, product: str | None, link: str) -> tuple[str, str | None]:
    """(caption, title) for one platform: caption + hashtags (+ link where it's tappable),
    trimmed to the platform's limit at a word boundary. Title is for YouTube only."""
    tags = " ".join(hashtags(product, platform.hashtags_max))
    link_part = f"\n\n{link}" if platform.link_clickable else ""
    link_cost = X_LINK_LENGTH + 2 if (platform.id == "x" and link_part) else len(link_part)
    budget = platform.caption_max - link_cost - (len(tags) + 2 if tags else 0)
    body = text if len(text) <= budget else text[:budget].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    caption = body + (f"\n\n{tags}" if tags else "") + link_part
    title = None
    if platform.title_max:
        title = text if len(text) <= platform.title_max else \
            text[: platform.title_max - 1].rsplit(" ", 1)[0] + "…"
    return caption, title


# --- scheduling --------------------------------------------------------------------

def _caption_for_render(conn: psycopg.Connection, r: dict) -> str:
    if r.get("caption_id"):
        row = conn.execute("SELECT text FROM caption WHERE id=%s", (r["caption_id"],)).fetchone()
        if row:
            return row["text"]
    return (r["spec"] or {}).get("caption", "") or ""


def _candidates(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """SELECT r.id, r.asset_id, r.caption_id, r.spec, a.path
           FROM render r JOIN asset a ON a.id = r.asset_id
           WHERE r.qc_passed ORDER BY r.id""").fetchall()


def _pick(conn, platform: str, slot: datetime, cands: list[dict]) -> dict | None:
    """Best render for this platform and slot, or None."""
    used = {r["render_id"] for r in conn.execute(
        "SELECT render_id FROM post WHERE platform=%s", (platform,))}
    lo, hi = slot - timedelta(days=ASSET_GAP_DAYS), slot + timedelta(days=ASSET_GAP_DAYS)
    blocked_assets = {r["asset_id"] for r in conn.execute(
        """SELECT asset_id FROM post WHERE platform=%s AND status <> 'rejected'
             AND scheduled_at > %s AND scheduled_at < %s""", (platform, lo, hi))}
    last_used = {r["asset_id"]: r["last"] for r in conn.execute(
        "SELECT asset_id, max(scheduled_at) AS last FROM post WHERE platform=%s GROUP BY asset_id",
        (platform,))}
    used_elsewhere = {r["render_id"] for r in conn.execute(
        "SELECT render_id FROM post WHERE platform<>%s", (platform,))}
    pool = [c for c in cands if c["id"] not in used and c["asset_id"] not in blocked_assets
            and _caption_for_render(conn, c)]
    if not pool:
        return None
    never = datetime.min.replace(tzinfo=slot.tzinfo)
    # least recently used footage first; within it, a variant no other platform has yet
    pool.sort(key=lambda c: (last_used.get(c["asset_id"], never), c["id"] in used_elsewhere, c["id"]))
    return pool[0]


def schedule(conn: psycopg.Connection, start: date, days: int = 7,
             now: datetime | None = None) -> list[int]:
    """Fill every open slot from `start` for `days` days. Returns new post ids.
    Safe to re-run: filled slots are left alone."""
    zone = tz()
    now = now or datetime.now(zone)
    cands = _candidates(conn)
    new_ids = []
    for d in range(days):
        day = start + timedelta(days=d)
        for p in platforms():
            for t in p.post_times[: p.daily_cap]:
                hh, mm = (int(x) for x in t.split(":"))
                slot = datetime.combine(day, time(hh, mm), zone)
                if slot <= now:
                    continue
                taken = conn.execute("SELECT 1 FROM post WHERE platform=%s AND scheduled_at=%s",
                                     (p.id, slot)).fetchone()
                if taken:
                    continue
                r = _pick(conn, p.id, slot, cands)
                if r is None:
                    continue
                new_ids.append(_create_post(conn, p, r, slot))
    return new_ids


def _create_post(conn, p: Platform, r: dict, slot: datetime) -> int:
    product = product_for_asset(r["path"])
    text = _caption_for_render(conn, r)
    with conn.transaction():
        row = conn.execute(
            """INSERT INTO post (render_id, asset_id, platform, caption_text, scheduled_at,
                                 idempotency_key)
               VALUES (%s,%s,%s,'',%s,%s) RETURNING id""",
            (r["id"], r["asset_id"], p.id, slot, f"post:{p.id}:{r['id']}")).fetchone()
        link = tracked_link(product, p.id, row["id"])
        caption, title = shape_caption(text, p, product, link)
        conn.execute("UPDATE post SET caption_text=%s, title=%s, link_url=%s WHERE id=%s",
                     (caption, title, link, row["id"]))
        conn.execute(
            """INSERT INTO approval (item_type, item_id, summary) VALUES ('post', %s, %s)
               ON CONFLICT DO NOTHING""",
            (str(row["id"]), f"{p.name} {slot:%a %b %d %H:%M}: {text[:120]}"))
    return row["id"]


def expire_missed(conn: psycopg.Connection, now: datetime | None = None) -> int:
    """Posts whose day has fully passed without being posted become 'skipped'."""
    now = now or datetime.now(tz())
    cur = conn.execute(
        """UPDATE post SET status='skipped'
           WHERE status IN ('planned','approved') AND scheduled_at < %s""",
        (now - timedelta(days=1),))
    return cur.rowcount


# --- review -------------------------------------------------------------------------

def _set_status(conn, post_id: int, status: str, note: str = "") -> None:
    approval_status = {"approved": "approved", "rejected": "rejected"}[status]
    with conn.transaction():
        conn.execute("UPDATE post SET status=%s WHERE id=%s AND status='planned'", (status, post_id))
        conn.execute(
            """UPDATE approval SET status=%s, decision_note=%s, decided_at=now()
               WHERE item_type='post' AND item_id=%s""",
            (approval_status, note.strip() or None, str(post_id)))


def pending_posts(conn: psycopg.Connection, limit: int = 50) -> list[dict]:
    return conn.execute(
        """SELECT p.*, r.output_path FROM post p JOIN render r ON r.id = p.render_id
           WHERE p.status='planned' ORDER BY p.scheduled_at, p.platform LIMIT %s""",
        (limit,)).fetchall()


def review(conn: psycopg.Connection, ask: Callable[[str], str] = input,
           show: Callable[[str], None] = print) -> dict:
    """a=approve, r=reject (+reason), A=approve ALL remaining, s=skip, q=quit."""
    stats = {"approved": 0, "rejected": 0, "skipped": 0}
    items = pending_posts(conn)
    if not items:
        show("No posts waiting for approval. Run `schedule` first.")
        return stats
    zone = tz()
    approve_rest = False
    for i, p in enumerate(items, 1):
        if not approve_rest:
            when = p["scheduled_at"].astimezone(zone)
            show(f"\n[{i}/{len(items)}]  {p['platform'].upper()}  {when:%a %b %d, %I:%M %p}")
            show(f"    video: {Path(p['output_path']).name}")
            if p["title"]:
                show(f"    title: {p['title']}")
            show("    caption:\n      " + p["caption_text"].replace("\n", "\n      "))
            choice = ask("  a = approve, r = reject, A = approve all remaining, s = skip, q = quit: ").strip()
            if choice == "q":
                break
            if choice == "A":
                approve_rest = True
            elif choice == "r":
                _set_status(conn, p["id"], "rejected", ask("  why? (one line): "))
                stats["rejected"] += 1
                continue
            elif choice != "a":
                stats["skipped"] += 1
                continue
        _set_status(conn, p["id"], "approved")
        stats["approved"] += 1
    return stats


# --- posting kit -------------------------------------------------------------------

def kit_dir(settings: Settings) -> Path:
    return settings.root / "posting_kit"


def _place_video(src: Path, dest: Path) -> None:
    if dest.exists():
        return
    try:
        os.link(src, dest)          # instant, no extra disk space
    except OSError:
        shutil.copy2(src, dest)     # different drive or not allowed: copy


def export_kit(conn: psycopg.Connection, settings: Settings, day: date) -> Path | None:
    """Folder for `day`: one subfolder per approved post (in posting order) with the
    video and the exact text to paste. Re-running refreshes it; nothing is duplicated."""
    zone = tz()
    lo = datetime.combine(day, time(0, 0), zone)
    rows = conn.execute(
        """SELECT p.*, r.output_path FROM post p JOIN render r ON r.id = p.render_id
           WHERE p.status IN ('approved','posted') AND p.scheduled_at >= %s AND p.scheduled_at < %s
           ORDER BY p.scheduled_at, p.platform""", (lo, lo + timedelta(days=1))).fetchall()
    if not rows:
        return None
    by_id = {p.id: p for p in platforms()}
    folder = kit_dir(settings) / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    lines = [f"ONEWRLD posting kit for {day:%A %B %d, %Y}", "",
             "For each post: open its folder, upload video.mp4 to the platform, paste caption.txt",
             "(YouTube: paste title.txt as the title). Then mark it done so the system knows:",
             "    python -m onewrld posted <post number>", ""]
    for p in rows:
        when = p["scheduled_at"].astimezone(zone)
        plat = by_id.get(p["platform"])
        sub = folder / f"{when:%H%M}_{p['platform']}_post{p['id']}"
        sub.mkdir(exist_ok=True)
        _place_video(Path(p["output_path"]), sub / "video.mp4")
        (sub / "caption.txt").write_text(p["caption_text"] + "\n", encoding="utf-8")
        if p["title"]:
            (sub / "title.txt").write_text(p["title"] + "\n", encoding="utf-8")
        srt = Path(p["output_path"]).with_suffix(".srt")
        if srt.exists() and not (sub / "captions.srt").exists():
            shutil.copy2(srt, sub / "captions.srt")
        done = "  [POSTED]" if p["status"] == "posted" else ""
        lines.append(f"{when:%I:%M %p}  {plat.name if plat else p['platform']:<16} "
                     f"post {p['id']:<5} folder: {sub.name}{done}")
    (folder / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def mark_posted(conn: psycopg.Connection, post_id: int, url: str | None = None) -> bool:
    cur = conn.execute(
        """UPDATE post SET status='posted', posted_at=now(), external_url=COALESCE(%s, external_url)
           WHERE id=%s AND status IN ('approved','posted')""", (url, post_id))
    return cur.rowcount == 1


def upcoming(conn: psycopg.Connection, days: int = 7) -> list[dict]:
    now = datetime.now(tz())
    return conn.execute(
        """SELECT p.id, p.platform, p.scheduled_at, p.status, p.caption_text
           FROM post p WHERE p.scheduled_at >= %s AND p.scheduled_at < %s
           ORDER BY p.scheduled_at, p.platform""",
        (now - timedelta(hours=12), now + timedelta(days=days))).fetchall()
