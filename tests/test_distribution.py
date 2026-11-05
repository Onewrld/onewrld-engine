"""Phase 5.1: platform captions, tracked links, scheduling rules, approval, posting kit,
and the adapter layer that automatic posting will use."""

from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from psycopg.types.json import Jsonb

from onewrld import adapters, distribution, safety
from onewrld.errors import HaltedError

SWEATS = "onewrld-fall-of-icarus-sweatpants"
P = {p.id: p for p in distribution.platforms()}


# --- captions and links (no database) ---------------------------------------------

def test_tracked_link_carries_platform_post_and_collection():
    url = distribution.tracked_link(SWEATS, "tiktok", 42)
    u = urlparse(url)
    assert u.path == f"/products/{SWEATS}"
    q = parse_qs(u.query)
    assert q["utm_source"] == ["tiktok"] and q["utm_content"] == ["post42"]
    assert q["utm_campaign"] == ["fall_of_icarus"] and q["utm_medium"] == ["social"]


def test_unknown_product_links_to_store_home():
    assert urlparse(distribution.tracked_link(None, "x", 1)).path == "/"


def test_instagram_has_hashtags_but_no_dead_link():
    cap, title = distribution.shape_caption("Heavy cotton sweats.", P["instagram"], SWEATS, "https://l")
    assert "#onewrld" in cap and "#fallofIcarus" in cap
    assert "https://" not in cap and title is None


def test_x_fits_280_counting_link_as_23():
    long = "Heavy cotton sweats cut wide from the knee down. " * 12
    link = "https://onewrld.us/products/x?" + "a" * 120  # long real URL; X shortens it to 23
    cap, _ = distribution.shape_caption(long, P["x"], SWEATS, link)
    visible = cap.replace(link, "x" * distribution.X_LINK_LENGTH)
    assert len(visible) <= 280
    assert cap.endswith(link) and "…" in cap


def test_youtube_gets_short_title_and_link():
    text = "Embroidered on the chest. Printed across the back. Built to hold its shape for years and years of wear."
    cap, title = distribution.shape_caption(text, P["youtube"], None, "https://onewrld.us/")
    assert title and len(title) <= 100 and title.endswith("…")
    assert "https://onewrld.us/" in cap


# --- scheduling (database) -----------------------------------------------------------

def _seed(conn, tmp_path, assets=3, variants=2, folder=SWEATS):
    """Fake finished renders (real files, tiny) for `assets` clips with `variants` each."""
    (tmp_path / folder).mkdir(exist_ok=True)
    for a in range(assets):
        src = tmp_path / folder / f"clip{a}.mp4"
        src.write_bytes(b"src")
        aid = conn.execute(
            """INSERT INTO asset (sha256, path, duration, width, height, has_audio)
               VALUES (%s,%s,10,1080,1920,true) RETURNING id""", (f"sha{a}", str(src))).fetchone()["id"]
        for v in range(variants):
            out = tmp_path / f"out_{a}_{v}.mp4"
            out.write_bytes(b"video")
            conn.execute(
                """INSERT INTO render (asset_id, render_key, spec, output_path, qc_passed)
                   VALUES (%s,%s,%s,%s,true)""",
                (aid, f"k{a}{v}", Jsonb({"caption": f"Caption {a}-{v}. Heavy cotton."}), str(out)))


NOW = datetime(2026, 11, 9, 8, 0, tzinfo=distribution.tz())  # a Monday morning
START = NOW.date()


def _posts(conn):
    return conn.execute("SELECT * FROM post ORDER BY scheduled_at").fetchall()


def test_schedule_respects_caps_and_asset_spacing(conn, tmp_path):
    _seed(conn, tmp_path, assets=3, variants=2)
    ids = distribution.schedule(conn, START, days=7, now=NOW)
    posts = _posts(conn)
    assert len(ids) == len(posts) > 0
    per_day = {}
    for p in posts:
        key = (p["platform"], p["scheduled_at"].astimezone(distribution.tz()).date())
        per_day[key] = per_day.get(key, 0) + 1
    assert max(per_day.values()) <= 1                                 # daily cap 1
    for plat in P:                                                    # same footage once/week/platform
        assets = [p["asset_id"] for p in posts if p["platform"] == plat]
        assert len(assets) == len(set(assets)) == 3
    # different platforms get different variants of the same clip where possible
    by_asset = {}
    for p in posts:
        by_asset.setdefault(p["asset_id"], set()).add(p["render_id"])
    assert all(len(v) == 2 for v in by_asset.values())


def test_schedule_is_idempotent_and_skips_past_slots(conn, tmp_path):
    _seed(conn, tmp_path, assets=10, variants=1)
    first = distribution.schedule(conn, START, days=3, now=NOW)
    assert distribution.schedule(conn, START, days=3, now=NOW) == []   # nothing new
    late = NOW.replace(hour=23)
    assert all(p["scheduled_at"] > NOW for p in _posts(conn))
    conn.execute("DELETE FROM approval WHERE item_type='post'")
    conn.execute("DELETE FROM post")
    distribution.schedule(conn, START, days=1, now=late)              # all of today's slots passed
    assert _posts(conn) == []
    assert first


def test_posts_need_approval_and_review_records_reasons(conn, tmp_path):
    _seed(conn, tmp_path, assets=2, variants=1)
    distribution.schedule(conn, START, days=1, now=NOW)
    n = len(_posts(conn))
    answers = iter(["r", "wrong vibe", "A"])
    st = distribution.review(conn, ask=lambda q: next(answers), show=lambda m: None)
    assert st == {"approved": n - 1, "rejected": 1, "skipped": 0}
    note = conn.execute("SELECT decision_note FROM approval WHERE item_type='post' AND status='rejected'"
                        ).fetchone()["decision_note"]
    assert note == "wrong vibe"


def test_kit_exports_video_and_text_and_mark_posted(conn, tmp_path, db_settings):
    _seed(conn, tmp_path, assets=2, variants=1)
    distribution.schedule(conn, START, days=1, now=NOW)
    distribution.review(conn, ask=lambda q: "A", show=lambda m: None)
    folder = distribution.export_kit(conn, db_settings, START)
    subs = sorted(d for d in folder.iterdir() if d.is_dir())
    assert len(subs) == len(_posts(conn))
    for d in subs:
        assert (d / "video.mp4").read_bytes() == b"video"
        assert (d / "caption.txt").read_text().strip()
    assert distribution.export_kit(conn, db_settings, START) == folder   # safe to re-run
    pid = _posts(conn)[0]["id"]
    assert distribution.mark_posted(conn, pid, "https://tiktok.com/x")
    assert "[POSTED]" in (distribution.export_kit(conn, db_settings, START) / "README.txt").read_text()


def test_unapproved_post_cannot_be_marked_posted(conn, tmp_path):
    _seed(conn, tmp_path, assets=1, variants=1)
    distribution.schedule(conn, START, days=1, now=NOW)
    assert not distribution.mark_posted(conn, _posts(conn)[0]["id"])


def test_missed_posts_expire(conn, tmp_path):
    _seed(conn, tmp_path, assets=1, variants=1)
    distribution.schedule(conn, START, days=1, now=NOW)
    assert distribution.expire_missed(conn, now=NOW + timedelta(days=3)) >= 1
    assert {p["status"] for p in _posts(conn)} == {"skipped"}


# --- adapters: the path automatic posting will take --------------------------------

class FakeService(adapters.Adapter):
    name, automatic = "fake", True

    def __init__(self):
        self.calls = 0

    def publish(self, settings, post, video_path):
        self.calls += 1
        return f"ext{post['id']}", f"https://example.com/{post['id']}"


@pytest.fixture
def fake_service(conn, tmp_path):
    svc = FakeService()
    adapters.register(svc)
    _seed(conn, tmp_path, assets=1, variants=1)
    distribution.schedule(conn, START, days=1, now=NOW)
    distribution.review(conn, ask=lambda q: "A", show=lambda m: None)
    conn.execute("UPDATE post SET adapter='fake'")
    yield svc
    adapters.ADAPTERS.pop("fake", None)


def test_dry_run_publishes_nothing(fake_service, conn, make_settings, db_settings):
    from dataclasses import replace
    s = replace(db_settings, mode="dry_run")
    st = adapters.publish_due(s, conn, now=NOW + timedelta(days=1))
    assert st["dry_run"] >= 1 and fake_service.calls == 0
    assert {p["status"] for p in _posts(conn)} == {"approved"}


def test_live_publishes_once_only(fake_service, conn, db_settings):
    from dataclasses import replace
    s = replace(db_settings, mode="live")
    later = NOW + timedelta(days=1)
    first = adapters.publish_due(s, conn, now=later)
    again = adapters.publish_due(s, conn, now=later)
    assert first["published"] >= 1 and again["published"] == 0
    assert fake_service.calls == first["published"]                  # never double-posted
    assert all(p["external_id"] for p in _posts(conn))


def test_kill_switch_blocks_publishing(fake_service, conn, db_settings):
    from dataclasses import replace
    s = replace(db_settings, mode="live")
    safety.halt(s, "test")
    try:
        with pytest.raises(HaltedError):
            adapters.publish_due(s, conn, now=NOW + timedelta(days=1))
        assert fake_service.calls == 0
    finally:
        safety.resume(s, "done")
