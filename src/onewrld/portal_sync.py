"""Portal sync: turns affiliate uploads into finished posts in the owner's Approve screen.

`python -m onewrld portal sync` does, for each new upload (oldest first, a few at a time):
  1. marks it "being edited" (so the affiliate sees progress)
  2. downloads the clip from Supabase Storage to media/portal/
  3. edits it with the Video Studio: a main version + alternates, each with a different
     approved hook (on screen), look and crop, all quality-checked
  4. uploads the finished versions to the private "packs" storage folder
  5. creates the post ("pack") with the approved caption, so it appears under Approve
  6. deletes the raw upload from Supabase to save space (free plan: 1 GB); the original
     stays on this PC in media/portal/
A failure marks the upload "couldn't be edited", raises an alert, and moves on.

Talks to Supabase two ways: the database directly (DATABASE_URL, same project) and the
Storage API over HTTPS with the secret key from .env.
"""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import psycopg

from onewrld import alerts, studio, videos
from onewrld.config import Settings
from onewrld.errors import PermanentError, RetryableError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)
VERSIONS = 3            # main + 2 alternates per upload (D-065)
BATCH = 5               # uploads handled per sync run (bounded)
STALE_MINUTES = 60      # an upload stuck "being edited" this long gets retried


class Storage:
    """Minimal Supabase Storage client using the secret key (bypasses security rules,
    so it only ever runs on the owner's PC)."""

    def __init__(self, url: str, key: str, opener=urllib.request.urlopen):
        if not (url and key):
            raise PermanentError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env (RUNBOOK 19).")
        self.base = url.rstrip("/") + "/storage/v1/object"
        self.key = key
        self.open = opener

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"apikey": self.key}
        if not self.key.startswith("sb_secret_"):   # legacy JWT keys also go as Bearer (D-064)
            h["Authorization"] = f"Bearer {self.key}"
        h.update(extra or {})
        return h

    def _call(self, req: urllib.request.Request):
        try:
            return self.open(req, timeout=120)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 504):
                raise RetryableError(f"Supabase Storage busy ({e.code}): {body}") from None
            raise PermanentError(f"Supabase Storage refused ({e.code}): {body}") from None
        except OSError as e:
            raise RetryableError(f"Couldn't reach Supabase Storage: {e}") from None

    def download(self, bucket: str, key: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(f"{self.base}/{bucket}/{quote(key)}", headers=self._headers())
        with self._call(req) as r, open(dest, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        return dest

    def upload(self, bucket: str, key: str, path: Path) -> None:
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        req = urllib.request.Request(
            f"{self.base}/{bucket}/{quote(key)}", method="POST", data=path.read_bytes(),
            headers=self._headers({"Content-Type": ctype, "x-upsert": "true"}))
        with self._call(req):
            pass

    def delete(self, bucket: str, key: str) -> None:
        req = urllib.request.Request(
            f"{self.base}/{bucket}", method="DELETE", data=json.dumps({"prefixes": [key]}).encode(),
            headers=self._headers({"Content-Type": "application/json"}))
        with self._call(req):
            pass


def claim(conn: psycopg.Connection, schema: str, limit: int = BATCH) -> list[dict]:
    """Take the next uploads to edit (and retry ones stuck mid-edit). Two PCs running sync
    at once can never take the same upload."""
    with conn.transaction():
        conn.execute(
            f"""UPDATE {schema}.submissions SET status='uploaded'
                WHERE status='processing' AND claimed_at < now() - make_interval(mins => %s)""",
            (STALE_MINUTES,))
        return conn.execute(
            f"""UPDATE {schema}.submissions SET status='processing', claimed_at=now()
                WHERE id IN (SELECT id FROM {schema}.submissions WHERE status='uploaded'
                             ORDER BY created_at LIMIT %s FOR UPDATE SKIP LOCKED)
                RETURNING *""", (limit,)).fetchall()


def _render_versions(settings: Settings, conn: psycopg.Connection, clip: Path,
                     product: str | None) -> list[dict]:
    from onewrld.worker import run_worker
    asset = videos.register_asset(conn, clip)
    job_ids = videos.plan(conn, asset, VERSIONS - 1, product=product)
    run_worker(settings, max_jobs=len(job_ids), max_seconds=3600, only_ids=job_ids)
    return conn.execute(
        """SELECT r.* FROM render r JOIN job j ON j.idempotency_key = 'render:' || r.render_key
           WHERE j.id = ANY(%s) AND r.qc_passed ORDER BY r.id""", (job_ids,)).fetchall()


def _caption_text(conn: psycopg.Connection, render: dict) -> str:
    if render.get("caption_id"):
        row = conn.execute("SELECT text FROM caption WHERE id=%s", (render["caption_id"],)).fetchone()
        if row:
            return row["text"]
    return (render["spec"] or {}).get("caption") or ""


def process_one(settings: Settings, conn: psycopg.Connection, store: Storage, sub: dict,
                schema: str = "public") -> int:
    """Edit one upload into a pack. Returns the pack id."""
    local = settings.root / "media" / "portal" / (sub["product_handle"] or "untagged") / \
        f"{sub['id']}_{Path(sub['storage_key']).name}"
    if not local.exists():
        store.download("uploads", sub["storage_key"], local)
    renders = _render_versions(settings, conn, local, sub["product_handle"])
    if not renders:
        raise PermanentError("no version passed the quality check")
    keys, hooks = [], []
    for r in renders:
        key = f"{sub['id']}/{r['render_key']}.mp4"
        store.upload("packs", key, Path(r["output_path"]))
        keys.append(key)
        hooks.append((r["spec"] or {}).get("caption") or "")
    caption = _caption_text(conn, renders[0]) or hooks[0]
    if not caption:
        raise PermanentError("no approved caption for this product yet: approve captions, then retry")
    with conn.transaction():
        pack = conn.execute(
            f"""INSERT INTO {schema}.packs (submission_id, video_key, hook_text, caption_base,
                                           alt_video_keys, alt_hooks)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (submission_id) DO UPDATE SET video_key=EXCLUDED.video_key,
                    hook_text=EXCLUDED.hook_text, caption_base=EXCLUDED.caption_base,
                    alt_video_keys=EXCLUDED.alt_video_keys, alt_hooks=EXCLUDED.alt_hooks
                RETURNING id""",
            (sub["id"], keys[0], hooks[0] or None, caption, keys[1:], hooks[1:])).fetchone()
        conn.execute(f"UPDATE {schema}.submissions SET status='ready', error=NULL WHERE id=%s",
                     (sub["id"],))
    try:
        store.delete("uploads", sub["storage_key"])   # free space; the original is on this PC
    except (PermanentError, RetryableError) as e:
        log.warning(f"Couldn't delete raw upload {sub['storage_key']}: {e}")
    return pack["id"]


def sync(settings: Settings, conn: psycopg.Connection, store: Storage | None = None,
         schema: str = "public", limit: int = BATCH) -> dict:
    store = store or Storage(settings.supabase_url, settings.supabase_service_key)
    studio.require_ffmpeg()
    stats = {"ready": 0, "failed": 0}
    for sub in claim(conn, schema, limit):
        try:
            pid = process_one(settings, conn, store, sub, schema)
            stats["ready"] += 1
            log.info(f"Upload {sub['id']} → pack {pid}")
        except Exception as e:  # never stop the whole run for one bad clip
            msg = str(e)[:500]
            status = "uploaded" if isinstance(e, RetryableError) else "failed"
            conn.execute(f"UPDATE {schema}.submissions SET status=%s, error=%s WHERE id=%s",
                         (status, msg, sub["id"]))
            if status == "failed":
                alerts.raise_alert(conn, "warn", "portal:sync",
                                   f"Upload {sub['id']} ({sub['original_name']}) couldn't be edited: {msg}")
            stats["failed"] += 1
    return stats
