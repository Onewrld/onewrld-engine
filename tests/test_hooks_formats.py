"""Hook & Format Library: library quality, shot lists, hook import/review, and hooks on videos."""

import shutil
import tomllib

import pytest

from onewrld import brand, captions, products, shotlist, studio, videos

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
HOOK_TYPES = {"statement", "founder", "process", "detail", "icarus", "discipline", "contrast",
              "list", "pov"}
VALID_TAGS = {p["handle"] for p in products.catalog()} | {"brand", "collection:fall_of_icarus",
                                                         "collection:signature"}


def _hooks():
    return tomllib.loads((brand.BRAND_DIR / "hooks.toml").read_text(encoding="utf-8"))["hooks"]


# --- the libraries themselves ---------------------------------------------------------

def test_hook_library_is_big_clean_and_on_brand():
    hooks = _hooks()
    assert len(hooks) >= 100
    texts = [h["text"] for h in hooks]
    assert len(texts) == len(set(texts))
    for h in hooks:
        assert h["type"] in HOOK_TYPES and h["product"] in VALID_TAGS, h
        s = brand.score_caption(h["text"])
        assert s.passes and s.score >= 90, (h["text"], s.reasons)
        low = h["text"].lower()
        assert "fly anyway" not in low and "flew anyway" not in low          # L-001
        assert not h["text"].rstrip().endswith("?")                          # statements (L-003)


def test_format_library_is_complete():
    fmts = shotlist.formats()
    assert len(fmts) >= 30
    assert len({f["id"] for f in fmts}) == len(fmts)
    for f in fmts:
        assert f["location"] in shotlist.LOCATION_ORDER
        assert f["products"] in set(shotlist.NEEDS) | {"any", "brand", "none"}
        assert set(f["hook_types"]) <= HOOK_TYPES and f["shots"] and f["seconds"] > 0


# --- shot lists --------------------------------------------------------------------

def test_shot_list_fits_time_and_orders_by_location():
    chosen = shotlist.plan(minutes=120)
    assert shotlist._total_minutes(chosen) <= 120
    order = [shotlist.LOCATION_ORDER[f["location"]] for f in chosen]
    assert order == sorted(order)                       # home, then outside, then gym
    assert any(f["talking"] for f in chosen)            # always a talking clip
    assert not any(f["drop_only"] for f in chosen)      # no drop teases unless asked


def test_shot_list_skips_formats_for_products_not_in_stock():
    stock = {"onewrld-fall-of-icarus-zip-hoodie"}       # sweats, hat, cup sold out
    ids = {f["id"] for f in shotlist.plan(minutes=480, stock=stock)}
    assert "F21" not in ids and "F11" not in ids and "F09" not in ids
    assert "F06" in ids


def test_drop_formats_only_when_asked():
    assert "F28" in {f["id"] for f in shotlist.plan(minutes=480, include_drop=True)}


def test_suggested_hooks_are_unique_and_match_the_product():
    chosen = shotlist.plan(minutes=240)
    used, by_text = set(), {h["text"]: h for h in _hooks()}
    for f in chosen:
        hs = shotlist.suggested_hooks(f, exclude=used)
        assert not (set(hs) & used)
        used.update(hs)
        target = shotlist.HOOK_PRODUCT.get(f["products"])
        for t in hs:
            if target:  # product formats never get unrelated brand lines
                assert by_text[t]["product"] in {target, "collection:fall_of_icarus"}, (f["id"], t)


def test_shot_list_file(tmp_path):
    from datetime import date
    out = shotlist.write(tmp_path, 120, date(2026, 11, 7))
    text = out.read_text()
    assert "SHOOT DAY" in text and "AT HOME" in text and "python -m onewrld batch" in text


# --- hooks in the database -------------------------------------------------------------

def test_hooks_import_separately_from_captions(conn):
    cap_id, _ = captions.add_caption(conn, "Ego is the fastest way down.", pillar="story")
    st = captions.import_hooks(conn, brand.BRAND_DIR / "hooks.toml")
    assert st["new"] == len(_hooks()) and st["blocked"] == 0
    rows = conn.execute("SELECT id, kind FROM caption WHERE text = 'Ego is the fastest way down.'"
                        ).fetchall()
    assert {r["kind"] for r in rows} == {"caption", "hook"}            # same words, two items
    assert captions.import_hooks(conn, brand.BRAND_DIR / "hooks.toml")["new"] == 0
    # caption review never shows hooks, and hook review never shows captions
    assert all(c["hook_type"] is None for c in captions.pending(conn, 500, "caption"))
    assert len(captions.pending(conn, 500, "hook")) == len(_hooks())
    assert cap_id


def test_hook_edit_stays_a_hook(conn):
    hid, _ = captions.add_caption(conn, "A warning you can wear.", kind="hook", hook_type="icarus",
                                  product="collection:fall_of_icarus")
    new_id = captions.record_edit(conn, hid, "A reminder you can wear.", "softer")
    row = conn.execute("SELECT kind, hook_type FROM caption WHERE id=%s", (new_id,)).fetchone()
    assert row["kind"] == "hook" and row["hook_type"] == "icarus"


def test_format_code_from_file_name():
    assert videos.format_from_name("F06_1.mp4") == "F06"
    assert videos.format_from_name("f12 take2.MOV") == "F12"
    assert videos.format_from_name("IMG_1234.mp4") is None
    assert videos.format_from_name("F123.mp4") is None


@needs_ffmpeg
def test_each_version_gets_a_different_hook_and_the_video_records_it(db_settings, conn):
    from onewrld.worker import run_worker

    def approve(text, kind="caption", product="onewrld-fall-of-icarus-zip-hoodie"):
        cid, _ = captions.add_caption(conn, text, kind=kind, product=product,
                                      hook_type="detail" if kind == "hook" else None,
                                      pillar="product")
        captions.decide(conn, cid, "approved")
        return cid

    cap = approve("Embroidered on the chest. Printed across the back.")
    h1 = approve("480 GSM. Feel that weight.", "hook")
    h2 = approve("Look closer at the stitching.", "hook")
    folder = db_settings.root / "media" / "inbox" / "onewrld-fall-of-icarus-zip-hoodie"
    clip = studio.make_test_clip(folder / "F06_weight.mp4", seconds=4.0)
    asset = videos.register_asset(conn, clip)
    assert asset["format_id"] == "F06"
    ids = videos.plan(conn, asset, variants=1, product="onewrld-fall-of-icarus-zip-hoodie")
    run_worker(db_settings, max_jobs=5, max_seconds=600, only_ids=ids)
    rows = conn.execute("SELECT hook_id, caption_id, format_id, spec FROM render ORDER BY id").fetchall()
    assert len(rows) == 2
    assert {r["hook_id"] for r in rows} == {h1, h2}                   # a different hook on each
    assert {r["spec"]["caption"] for r in rows} == {"480 GSM. Feel that weight.",
                                                     "Look closer at the stitching."}
    assert all(r["caption_id"] == cap and r["format_id"] == "F06" for r in rows)
