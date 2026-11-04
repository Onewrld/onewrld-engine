"""Videos: connects the Video Studio to the database and the job queue.

Flow for `python -m onewrld render clip.mp4`:
  1. register the clip as an asset (fingerprinted, so re-adding it is harmless)
  2. pick captions: the one you typed, or your APPROVED captions from the Brand Brain
  3. plan the main version + variants, and queue one render job per version
     (each job's idempotency key = asset + settings, so nothing renders twice)
  4. the worker runs the jobs; each finished file is quality-checked and recorded
A render that fails the quality check is recorded as failed and raises an alert.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from onewrld import studio
from onewrld.config import Settings
from onewrld.errors import PermanentError
from onewrld.jobs import enqueue, handler


def renders_dir(settings: Settings) -> Path:
    return settings.root / "renders"


def register_asset(conn: psycopg.Connection, path: Path) -> dict:
    path = path.resolve()
    if not path.exists():
        raise PermanentError(f"File not found: {path}")
    info = studio.probe(path)
    sha = studio.file_sha(path)
    row = conn.execute(
        """INSERT INTO asset (sha256, path, duration, width, height, has_audio)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (sha256) DO UPDATE SET path = EXCLUDED.path
           RETURNING *""",
        (sha, str(path), info["duration"], info["width"], info["height"], info["has_audio"])
    ).fetchone()
    return row


def approved_captions(conn: psycopg.Connection, limit: int = 10) -> list[dict]:
    """Approved captions, product ones first (they have the best approval rate, L-008)."""
    return conn.execute(
        """SELECT c.id, c.text FROM approval a JOIN caption c ON c.id = a.item_id::bigint
           WHERE a.item_type='caption' AND a.status='approved' AND NOT c.blocked
           ORDER BY (c.pillar = 'product') DESC, a.decided_at DESC LIMIT %s""",
        (limit,)).fetchall()


def plan(conn: psycopg.Connection, asset: dict, variants: int,
         caption_text: str | None = None, max_seconds: float = 30.0,
         talk: bool = False) -> list[int]:
    """Queue the main render + variants. Returns job ids (existing ones are reused).
    talk=True: a talking clip. On-screen captions follow the speech word by word and pauses
    are cut; the chosen caption is kept as the post's text."""
    if caption_text:
        caps = [{"id": None, "text": caption_text}]
    else:
        caps = approved_captions(conn) or [{"id": None, "text": ""}]
    base = studio.RenderSpec(max_seconds=max_seconds, speech_captions=talk, cut_silence=talk)
    specs = studio.variant_specs(base, [c["text"] for c in caps], variants, asset["duration"])
    job_ids = []
    for i, spec in enumerate(specs):
        cap = caps[i % len(caps)]
        key = spec.key(asset["sha256"])
        job_id, _ = enqueue(conn, "video.render",
                            {"asset_id": asset["id"], "spec": asdict(spec), "caption_id": cap["id"]},
                            idempotency_key=f"render:{key}", max_attempts=2)
        job_ids.append(job_id)
    return job_ids


@handler("video.render")
def render_job(settings: Settings, payload: dict):
    from onewrld import db

    with db.connect(settings) as conn:
        asset = conn.execute("SELECT * FROM asset WHERE id=%s", (payload["asset_id"],)).fetchone()
    if asset is None:
        raise PermanentError(f"asset {payload['asset_id']} not found")
    src = Path(asset["path"])
    if not src.exists():
        raise PermanentError(f"source file moved or deleted: {src}")
    spec = studio.RenderSpec(**payload["spec"])
    result = studio.render(src, spec, renders_dir(settings))
    qc = result["qc"]
    with db.connect(settings) as conn:
        conn.execute(
            """INSERT INTO render (asset_id, render_key, caption_id, spec, output_path, qc_passed, qc)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (render_key) DO UPDATE SET output_path=EXCLUDED.output_path,
                   qc_passed=EXCLUDED.qc_passed, qc=EXCLUDED.qc""",
            (asset["id"], result["key"], payload.get("caption_id"), Jsonb(result["spec"]),
             result["output"], qc["passed"],
             Jsonb({"checks": qc["checks"], "lufs": qc["lufs"]})))
    if not qc["passed"]:
        failed = [k for k, ok in qc["checks"].items() if not ok]
        raise PermanentError(f"quality check failed: {', '.join(failed)}")
    return {"output": result["output"], "qc_passed": True}


def recent(conn: psycopg.Connection, limit: int = 20) -> list[dict]:
    return conn.execute(
        """SELECT r.id, r.output_path, r.qc_passed, r.spec, r.qc, a.path AS source
           FROM render r JOIN asset a ON a.id = r.asset_id
           ORDER BY r.id DESC LIMIT %s""", (limit,)).fetchall()
