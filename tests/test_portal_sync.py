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


# --- high volume (D-067) ----------------------------------------------------------------

def test_one_run_drains_everything_waiting_within_its_bounds(team, db_settings, monkeypatch):
    conn, s, ids = team
    subs = [_upload(conn, s, ids["blake"], f"{i}.mp4") for i in range(7)]
    done = []
    monkeypatch.setattr(portal_sync, "process_one", lambda st, c, store, sub, schema, v: done.append(sub["id"]) or 1)
    monkeypatch.setattr(studio, "require_ffmpeg", lambda: None)
    assert portal_sync.sync(db_settings, conn, FakeStorage(), schema=s, limit=2) == {"ready": 7, "failed": 0}
    assert sorted(done) == sorted(subs)                                  # 7 uploads, batches of 2, one run
    more = [_upload(conn, s, ids["blake"], f"m{i}.mp4") for i in range(5)]
    assert portal_sync.sync(db_settings, conn, FakeStorage(), schema=s, max_uploads=3)["ready"] == 3
    left = conn.execute(f"SELECT count(*) AS n FROM {s}.submissions WHERE status='uploaded'").fetchone()["n"]
    assert left == 2 and set(more) & set(done)                           # cap respected; rest next run


def test_network_trouble_stops_claiming_more(team, db_settings, monkeypatch):
    conn, s, ids = team
    for i in range(6):
        _upload(conn, s, ids["blake"], f"{i}.mp4")
    calls = []

    def flaky(*a):
        calls.append(1)
        raise RetryableError("Supabase busy")
    monkeypatch.setattr(portal_sync, "process_one", flaky)
    monkeypatch.setattr(studio, "require_ffmpeg", lambda: None)
    portal_sync.sync(db_settings, conn, FakeStorage(), schema=s, limit=2)
    assert len(calls) == 2                                               # one batch, then it stops
    assert conn.execute(f"SELECT count(*) AS n FROM {s}.submissions WHERE status='uploaded'").fetchone()["n"] == 6


def test_two_syncs_never_run_at_once(team, db_settings, monkeypatch):
    import psycopg
    conn, s, ids = team
    _upload(conn, s, ids["blake"])
    monkeypatch.setattr(studio, "require_ffmpeg", lambda: None)
    with psycopg.connect(db_settings.database_url, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (portal_sync.LOCK_KEY,))   # a run in progress
        assert portal_sync.sync(db_settings, conn, FakeStorage(), schema=s) == {"ready": 0, "failed": 0, "busy": 1}
    row = conn.execute(f"SELECT status FROM {s}.submissions").fetchone()
    assert row["status"] == "uploaded"


def test_one_version_per_affiliate_within_limits(team, db_settings):
    import dataclasses
    conn, s, ids = team
    assert portal_sync.versions_for(db_settings, conn, s) == 3              # 2 affiliates: still 3
    for i in range(8):
        conn.execute(f"INSERT INTO {s}.profiles (id, email, display_name) VALUES (gen_random_uuid(), %s, 'X')",
                     (f"x{i}@example.com",))
    assert portal_sync.versions_for(db_settings, conn, s) == 6              # 10 affiliates, default max 6
    big = dataclasses.replace(db_settings, portal_max_versions=10)
    assert portal_sync.versions_for(big, conn, s) == 10


def test_sync_refuses_when_portal_is_behind(team, db_settings):
    conn, s, ids = team
    conn.execute("DELETE FROM schema_migrations WHERE name=%s", (f"portal:{s}:0004_volume.sql",))
    with pytest.raises(PermanentError, match="portal setup"):
        portal_sync.sync(db_settings, conn, FakeStorage(), schema=s)


def test_status_shows_the_whole_pipeline(team):
    conn, s, ids = team
    _upload(conn, s, ids["blake"])
    st = portal_sync.status(conn, s)
    assert st["uploads"] == {"uploaded": 1} and st["spare_versions"] == 0
    assert {t["name"]: (t["waiting"], t["max_open"]) for t in st["team"]} == {"Blake": (0, 5), "Jess": (0, 5)}


def test_waiting_email_at_most_once_an_hour(db_settings, monkeypatch):
    import dataclasses
    from onewrld import db, notify
    sent = []
    monkeypatch.setattr(notify, "send_email", lambda st, subj, body: sent.append((subj, body)))
    st = dataclasses.replace(db_settings, smtp_user="a@x.com", smtp_app_password="p", alert_email="a@x.com",
                             portal_url="https://team.example")
    with db.connect(db_settings) as conn:
        conn.execute("DELETE FROM notification")
        assert notify.portal_waiting_email(st, conn, 4, 2) == "sent"
        assert notify.portal_waiting_email(st, conn, 5, 1) == "held"
        conn.execute("DELETE FROM notification")
    assert "4 post(s) waiting" in sent[0][0] and "https://team.example" in sent[0][1]
