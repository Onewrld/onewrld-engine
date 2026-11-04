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
    if path.suffix.lower() in studio.IMAGE_EXTS:
        from PIL import Image
        with Image.open(path) as im:
            info = {"duration": 0.0, "width": im.width, "height": im.height, "has_audio": False}
    else:
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


def approved_captions(conn: psycopg.Connection, limit: int = 10,
                      product: str | None = None) -> list[dict]:
    """Approved captions, product ones first (they have the best approval rate, L-008).
    With `product`, only captions tagged for that product, its collection, or brand-wide."""
    from onewrld import products
    targets = products.caption_targets(product)
    return conn.execute(
        """SELECT c.id, c.text FROM approval a JOIN caption c ON c.id = a.item_id::bigint
           WHERE a.item_type='caption' AND a.status='approved' AND NOT c.blocked
             AND (%s::text[] IS NULL OR c.product = ANY(%s::text[]))
           ORDER BY (c.pillar = 'product') DESC, (c.product = %s) DESC, a.decided_at DESC
           LIMIT %s""",
        (targets, targets, product, limit)).fetchall()


STILL_SECONDS = 7.0


def plan(conn: psycopg.Connection, asset: dict, variants: int,
         caption_text: str | None = None, max_seconds: float = 30.0,
         talk: bool = False, product: str | None = None) -> list[int]:
    """Queue the main render + variants. Returns job ids (existing ones are reused).
    talk=True: a talking clip. On-screen captions follow the speech word by word and pauses
    are cut; the chosen caption is kept as the post's text."""
    if caption_text:
        caps = [{"id": None, "text": caption_text}]
    else:
        caps = approved_captions(conn, product=product) or [{"id": None, "text": ""}]
    still = Path(asset["path"]).suffix.lower() in studio.IMAGE_EXTS
    if still:
        max_seconds = min(max_seconds, STILL_SECONDS)
    base = studio.RenderSpec(max_seconds=max_seconds, speech_captions=talk, cut_silence=talk,
                             fit="contain" if still else "fill")
    src_seconds = max_seconds if still else asset["duration"]
    specs = studio.variant_specs(base, [c["text"] for c in caps], variants, src_seconds)
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


# --- batch: everything in media/products and media/inbox ------------------------------

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


def inbox_dir(settings: Settings) -> Path:
    return settings.root / "media" / "inbox"


def find_sources(settings: Settings, include_photos: bool = False) -> list[tuple[Path, str | None]]:
    """(file, product handle or None). Only real VIDEO clips by default: still photos made
    into videos looked cheap (owner verdict, M-011), so they're opt-in only.
    Clips go in media/inbox/ (or media/inbox/<handle>/ to tag a product)."""
    from onewrld import products
    out = []
    roots = [inbox_dir(settings)] + ([products.products_dir(settings)] if include_photos else [])
    exts = VIDEO_EXTS | (studio.IMAGE_EXTS if include_photos else set())
    for root in roots:
        if not root.exists():
            continue
        for f in sorted(root.rglob("*")):
            if f.is_file() and f.suffix.lower() in exts:
                handle = f.parent.name if f.parent != root else None
                if handle and products.by_handle(handle) is None:
                    handle = None
                out.append((f, handle))
    return out


def plan_batch(conn: psycopg.Connection, settings: Settings, variants: int = 3,
               include_photos: bool = False) -> dict:
    jobs, uncaptioned = [], []
    for f, handle in find_sources(settings, include_photos):
        asset = register_asset(conn, f)
        if not approved_captions(conn, limit=1, product=handle):
            uncaptioned.append(f"{handle or 'untagged'}/{f.name}")
        jobs += plan(conn, asset, variants, product=handle)
    return {"job_ids": jobs, "uncaptioned": uncaptioned}


def visual_hash(video: Path, at: float = 0.4) -> int:
    """64-bit "difference hash" of one frame: similar-looking frames give similar hashes.
    Used to make sure two versions aren't near-copies of each other."""
    import io
    import subprocess
    from PIL import Image
    dur = studio.probe(video)["duration"]
    png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{dur * at:.2f}", "-i", str(video),
                          "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True).stdout
    img = Image.open(io.BytesIO(png)).convert("L").resize((9, 8))
    px = list(img.getdata()) if not hasattr(img, "get_flattened_data") else list(img.get_flattened_data())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


NEAR_DUPLICATE_BITS = 5  # hashes differing by 5 of 64 bits or fewer look nearly identical


def similarity_report(rows: list[dict]) -> list[str]:
    """Flag versions of the same source that look nearly identical AND share a caption."""
    from itertools import combinations
    by_asset: dict[int, list[dict]] = {}
    for r in rows:
        if r["qc_passed"]:
            by_asset.setdefault(r["asset_id"], []).append(r)
    issues = []
    for group in by_asset.values():
        hashes = {r["id"]: visual_hash(Path(r["output_path"])) for r in group}
        for a, b in combinations(group, 2):
            dist = bin(hashes[a["id"]] ^ hashes[b["id"]]).count("1")
            if dist <= NEAR_DUPLICATE_BITS and a["spec"].get("caption") == b["spec"].get("caption"):
                issues.append(f"{Path(a['output_path']).name} and {Path(b['output_path']).name} "
                              f"look alike ({dist}/64 bits differ)")
    return issues
