"""Adapters: one per way of publishing a post. An adapter is a small class with one job,
publish(post) -> (external_id, url). Everything else (scheduling, approval, captions,
safety) is shared, so adding a platform or a posting service means adding one adapter.

- ManualAdapter: you post by hand from the posting kit (the default; works today).
- Automatic adapters (Phase 5.2: the posting service, Meta's API) register themselves
  here and are always called through safety.outward_action, so the kill switch and
  dry-run mode apply to every real post.
"""

from __future__ import annotations

from datetime import datetime

import psycopg

from onewrld import safety
from onewrld.config import Settings
from onewrld.errors import PermanentError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)


class Adapter:
    name = "base"
    automatic = False

    def publish(self, settings: Settings, post: dict, video_path: str) -> tuple[str, str | None]:
        raise NotImplementedError


class ManualAdapter(Adapter):
    """Nothing is sent anywhere: the post goes into the day's posting kit."""
    name = "manual"
    automatic = False


ADAPTERS: dict[str, Adapter] = {"manual": ManualAdapter()}


def register(adapter: Adapter) -> None:
    ADAPTERS[adapter.name] = adapter


def publish_due(settings: Settings, conn: psycopg.Connection, now: datetime | None = None) -> dict:
    """Publish approved, due posts whose adapter is automatic. Idempotent: a post that has
    an external_id is never published again. Manual posts are left for the kit."""
    stats = {"published": 0, "dry_run": 0, "manual": 0}
    due = conn.execute(
        """SELECT p.*, r.output_path FROM post p JOIN render r ON r.id = p.render_id
           WHERE p.status='approved' AND p.scheduled_at <= COALESCE(%s, now())
             AND p.external_id IS NULL ORDER BY p.scheduled_at""", (now,)).fetchall()
    for post in due:
        adapter = ADAPTERS.get(post["adapter"])
        if adapter is None:
            raise PermanentError(f"no adapter named '{post['adapter']}'")
        if not adapter.automatic:
            stats["manual"] += 1
            continue
        result = safety.outward_action(
            settings, f"publish:{post['platform']}",
            lambda: adapter.publish(settings, post, post["output_path"]),
            details={"post_id": post["id"], "platform": post["platform"]})
        if result is None:  # dry run: nothing sent
            stats["dry_run"] += 1
            continue
        external_id, url = result
        conn.execute(
            """UPDATE post SET status='posted', posted_at=now(), external_id=%s, external_url=%s
               WHERE id=%s AND external_id IS NULL""", (external_id, url, post["id"]))
        stats["published"] += 1
    return stats
