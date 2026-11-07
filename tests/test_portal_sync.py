"""Portal sync: uploads become finished posts. Real video editing, fake Supabase Storage."""

import io
import json
import shutil
import urllib.error

import pytest

from onewrld import captions, portal_sync, studio
from onewrld.errors import PermanentError, RetryableError
from test_portal import pdb, team  # noqa: F401  (shared fixtures: portal in a throwaway schema)

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
HOODIE = "onewrld-fall-of-icarus-zip-hoodie"


class FakeStorage:
    """Stands in for Supabase Storage: serves a test clip, records uploads and deletes."""

    def __init__(self, clip=None, fail=None):
        self.clip, self.fail = clip, fail
        self.uploaded, self.deleted = {}, []

    def download(self, bucket, key, dest):
        if self.fail:
            raise self.fail
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.clip, dest)
        return dest

    def upload(self, bucket, key, path):
        self.uploaded[f"{bucket}/{key}"] = path.stat().st_size

    def delete(self, bucket, key):
        self.deleted.append(f"{bucket}/{key}")


def _upload(conn, s, uid, name="gym_fit.mp4", product=HOODIE):
    return conn.execute(
        f"""INSERT INTO {s}.submissions (affiliate_id, storage_key, original_name, product_handle, consent_at)
            VALUES (%s, %s, %s, %s, now()) RETURNING id""",
        (uid, f"{uid}/{name}", name, product)).fetchone()["id"]


def _approve(conn, text, kind="caption"):
    cid, _ = captions.add_caption(conn, text, kind=kind, product=HOODIE, pillar="product",
                                  hook_type="detail" if kind == "hook" else None)
    captions.decide(conn, cid, "approved")


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    return studio.make_test_clip(tmp_path_factory.mktemp("c") / "raw.mp4", seconds=4.0)


@needs_ffmpeg
def test_upload_becomes_a_pack_with_three_versions(team, db_settings, clip):
    conn, s, ids = team
    _approve(conn, "Embroidered on the chest. Printed across the back.")
    for h in ("480 GSM. Feel that weight.", "Look closer at the stitching.", "Zip it up. Notice the weight."):
        _approve(conn, h, kind="hook")
    sub = _upload(conn, s, ids["blake"])
    store = FakeStorage(clip)
    stats = portal_sync.sync(db_settings, conn, store, schema=s)
    assert stats == {"ready": 1, "failed": 0}
    pack = conn.execute(f"SELECT * FROM {s}.packs WHERE submission_id=%s", (sub,)).fetchone()
    assert pack["status"] == "pending" and len(pack["alt_video_keys"]) == 2
    assert pack["caption_base"] == "Embroidered on the chest. Printed across the back."
    assert len({pack["hook_text"], *pack["alt_hooks"]}) == 3            # a different hook on each
    assert set(store.uploaded) == {f"packs/{k}" for k in [pack["video_key"], *pack["alt_video_keys"]]}
    assert store.deleted == [f"uploads/{ids['blake']}/gym_fit.mp4"]      # space freed
    sub_row = conn.execute(f"SELECT status FROM {s}.submissions WHERE id=%s", (sub,)).fetchone()
    assert sub_row["status"] == "ready"
    assert portal_sync.sync(db_settings, conn, store, schema=s) == {"ready": 0, "failed": 0}  # nothing twice


@needs_ffmpeg
def test_no_approved_caption_fails_clearly_and_alerts(team, db_settings, clip):
    conn, s, ids = team
    sub = _upload(conn, s, ids["jess"], product="onewrld-shaker-cup")
    stats = portal_sync.sync(db_settings, conn, FakeStorage(clip), schema=s)
    assert stats["failed"] == 1
    row = conn.execute(f"SELECT status, error FROM {s}.submissions WHERE id=%s", (sub,)).fetchone()
    assert row["status"] == "failed" and "approved caption" in row["error"]
    assert conn.execute("SELECT count(*) AS n FROM alert WHERE source='portal:sync'").fetchone()["n"] == 1


def test_network_trouble_retries_later(team, db_settings):
    conn, s, ids = team
    sub = _upload(conn, s, ids["blake"])
    store = FakeStorage(fail=RetryableError("Supabase busy"))
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    portal_sync.sync(db_settings, conn, store, schema=s)
    row = conn.execute(f"SELECT status FROM {s}.submissions WHERE id=%s", (sub,)).fetchone()
    assert row["status"] == "uploaded"                                   # will be picked up again


def test_stuck_uploads_are_retried_and_claims_never_overlap(team):
    conn, s, ids = team
    a = _upload(conn, s, ids["blake"], "a.mp4")
    b = _upload(conn, s, ids["blake"], "b.mp4")
    old = _upload(conn, s, ids["blake"], "old.mp4")   # uploaded long ago, editing JUST started
    conn.execute(f"UPDATE {s}.submissions SET created_at = now() - interval '5 hours' WHERE id=%s", (old,))
    conn.execute(f"UPDATE {s}.submissions SET status='processing', claimed_at = now() - interval '2 hours' WHERE id=%s", (a,))
    got = [r["id"] for r in portal_sync.claim(conn, s, limit=10)]
    assert sorted(got) == sorted([a, b, old])                            # crashed one retried
    assert portal_sync.claim(conn, s, limit=10) == []                    # in progress: never taken twice


# --- the real Storage client's requests (fake network) ------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_storage_client_headers_and_urls(tmp_path):
    seen = []

    def opener(req, timeout=None):
        seen.append((req.get_method(), req.full_url, {k.lower(): v for k, v in req.header_items()}, req.data))
        return _Resp(b"videobytes")
    st = portal_sync.Storage("https://abc.supabase.co/", "sb_secret_xyz", opener)
    st.download("uploads", "uid/my clip.mp4", tmp_path / "x.mp4")
    (tmp_path / "out.mp4").write_bytes(b"v")
    st.upload("packs", "1/a.mp4", tmp_path / "out.mp4")
    st.delete("uploads", "uid/my clip.mp4")
    assert (tmp_path / "x.mp4").read_bytes() == b"videobytes"
    assert seen[0][1] == "https://abc.supabase.co/storage/v1/object/uploads/uid/my%20clip.mp4"
    assert all(h["apikey"] == "sb_secret_xyz" and "authorization" not in h for _, _, h, _ in seen)
    assert seen[1][0] == "POST" and seen[1][2]["content-type"] == "video/mp4"
    assert seen[2][0] == "DELETE" and json.loads(seen[2][3]) == {"prefixes": ["uid/my clip.mp4"]}


def test_storage_errors_are_classified():
    def busy(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b"busy"))

    def denied(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "no", {}, io.BytesIO(b"denied"))
    with pytest.raises(RetryableError):
        portal_sync.Storage("https://a.supabase.co", "k", busy).delete("uploads", "x")
    with pytest.raises(PermanentError):
        portal_sync.Storage("https://a.supabase.co", "k", denied).delete("uploads", "x")
    with pytest.raises(PermanentError, match="SUPABASE_URL"):
        portal_sync.Storage("", "", denied)



def test_sync_refuses_when_database_is_behind(team, db_settings, monkeypatch):  # M-014
    from onewrld import db
    conn, s, ids = team
    sub = _upload(conn, s, ids["blake"])
    monkeypatch.setattr(db, "pending_migrations", lambda settings, c: [type("F", (), {"name": "0006_x.sql"})()])
    with pytest.raises(PermanentError, match="migrate"):
        portal_sync.sync(db_settings, conn, FakeStorage(), schema=s)
    row = conn.execute(f"SELECT status FROM {s}.submissions WHERE id=%s", (sub,)).fetchone()
    assert row["status"] == "uploaded"                  # untouched: not claimed, not failed


def test_retry_puts_failed_uploads_back(team):
    conn, s, ids = team
    a = _upload(conn, s, ids["blake"], "a.mp4")
    conn.execute(f"UPDATE {s}.submissions SET status='failed', error='x' WHERE id=%s", (a,))
    assert portal_sync.retry_failed(conn, s) == 1
    row = conn.execute(f"SELECT status, error FROM {s}.submissions WHERE id=%s", (a,)).fetchone()
    assert row["status"] == "uploaded" and row["error"] is None
