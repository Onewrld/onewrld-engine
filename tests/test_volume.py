"""Phase 4B.1: product catalog, photo download, photo-to-video, product-matched captions,
batch rendering and the near-duplicate check."""

import io
import shutil
import tomllib
from pathlib import Path

import pytest
from PIL import Image

from onewrld import brand, captions, products, studio, videos

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
HOODIE = "onewrld-fall-of-icarus-zip-hoodie"
SWEATS = "onewrld-fall-of-icarus-sweatpants"
HAT = "onewrld-acid-wash-signature-hat"


def _photo(path: Path, color=(70, 70, 70)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (900, 1100), (0, 0, 0, 0))  # transparent background like Photoroom
    img.paste(Image.new("RGBA", (600, 800), color + (255,)), (150, 150))
    img.save(path)
    return path


# --- catalog and caption files -------------------------------------------------------

def test_catalog_lists_in_stock_products_with_images():
    handles = {p["handle"] for p in products.catalog()}
    assert {HOODIE, SWEATS, HAT, "onewrld-shaker-cup"} <= handles
    assert all(p["images"] for p in products.catalog())


def test_caption_targets_cover_product_collection_and_brand():
    assert set(products.caption_targets(SWEATS)) == {SWEATS, "brand", "collection:fall_of_icarus"}
    assert products.caption_targets(None) is None


def test_every_caption_file_tags_valid_products():
    valid = {p["handle"] for p in products.catalog()} | {"brand", "collection:fall_of_icarus",
                                                         "collection:signature"}
    for f in brand.BRAND_DIR.glob("captions_*.toml"):
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        for c in data["captions"]:
            assert c.get("product", data.get("product")) in valid, (f.name, c["text"])


def test_batch3_captions_pass_brand_rules():
    data = tomllib.loads((brand.BRAND_DIR / "captions_batch3_products.toml").read_text(encoding="utf-8"))
    for c in data["captions"]:
        assert brand.score_caption(c["text"]).passes, c["text"]


def test_pull_images_downloads_once(make_settings, monkeypatch):
    s = make_settings()
    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(req, timeout=None):
        calls.append(req.full_url)
        return Resp(b"img")

    paths = products.pull_images(s, opener=fake_open)
    n = sum(len(p["images"]) for p in products.catalog())
    assert len(paths) == n and len(calls) == n
    products.pull_images(s, opener=fake_open)
    assert len(calls) == n  # nothing downloaded twice


# --- product-matched captions (database) ------------------------------------------

def _approve(conn, text, product, pillar="product"):
    cid, _ = captions.add_caption(conn, text, pillar=pillar, product=product)
    captions.decide(conn, cid, "approved")
    return cid


def test_captions_match_the_product(conn):
    _approve(conn, "Hoodie line.", HOODIE)
    _approve(conn, "Sweats line.", SWEATS)
    _approve(conn, "Set line.", "collection:fall_of_icarus")
    _approve(conn, "Brand line.", "brand", pillar="story")
    for_sweats = {c["text"] for c in videos.approved_captions(conn, product=SWEATS)}
    assert for_sweats == {"Sweats line.", "Set line.", "Brand line."}
    for_hat = {c["text"] for c in videos.approved_captions(conn, product=HAT)}
    assert for_hat == {"Brand line."}  # no hoodie or sweats lines on the hat
    assert len(videos.approved_captions(conn)) == 4  # untagged footage: anything approved


def test_reimport_retags_without_losing_approval(conn):
    cid = _approve(conn, "Wide from the knee down.", "collection:fall_of_icarus")
    again, created = captions.add_caption(conn, "Wide from the knee down.", product=SWEATS)
    assert again == cid and not created
    row = conn.execute("SELECT product FROM caption WHERE id=%s", (cid,)).fetchone()
    assert row["product"] == SWEATS
    st = conn.execute("SELECT status FROM approval WHERE item_id=%s", (str(cid),)).fetchone()
    assert st["status"] == "approved"


# --- photo to video ------------------------------------------------------------------

@needs_ffmpeg
def test_photo_becomes_a_passing_vertical_video(tmp_path):
    photo = _photo(tmp_path / "p.png")
    r = studio.render(photo, studio.RenderSpec(caption="480 GSM cotton.", max_seconds=4.0,
                                               zoom=1.05), tmp_path / "out")
    assert r["qc"]["passed"], r["qc"]["checks"]
    assert r["spec"]["fit"] == "contain"
    assert r["qc"]["info"]["duration"] == pytest.approx(4.0 + studio.END_CARD_SECONDS, abs=0.2)


def test_speech_on_a_photo_is_refused(tmp_path):
    from onewrld.errors import PermanentError
    with pytest.raises(PermanentError, match="photo"):
        studio.render(_photo(tmp_path / "p.png"), studio.RenderSpec(speech_captions=True), tmp_path)


# --- batch -------------------------------------------------------------------------

@needs_ffmpeg
def test_batch_renders_products_and_inbox_with_matching_captions(db_settings, conn):
    from onewrld.worker import run_worker

    root = db_settings.root
    _photo(root / "media" / "products" / SWEATS / "1.png", (90, 90, 90))
    _photo(root / "media" / "products" / HAT / "1.png", (120, 110, 100))
    studio.make_test_clip(root / "media" / "inbox" / "old_reel.mp4", seconds=4.0)
    _approve(conn, "Heavy cotton sweats. Cut wide from the knee down.", SWEATS)
    _approve(conn, "Hoodie only line.", HOODIE)

    sources = videos.find_sources(db_settings)
    assert {(p.name, h) for p, h in sources} == {("1.png", SWEATS), ("1.png", HAT),
                                                 ("old_reel.mp4", None)}
    plan = videos.plan_batch(conn, db_settings, variants=1)
    assert len(plan["job_ids"]) == 6                     # 3 sources x (main + 1 variant)
    assert any(HAT in u for u in plan["uncaptioned"])    # hat has no approved caption yet
    stats = run_worker(db_settings, max_jobs=10, max_seconds=900, only_ids=plan["job_ids"])
    assert stats["done"] == 6, stats

    rows = conn.execute("SELECT r.*, a.path FROM render r JOIN asset a ON a.id=r.asset_id").fetchall()
    for r in rows:
        cap = r["spec"]["caption"]
        if SWEATS in r["path"]:
            assert cap.startswith("Heavy cotton sweats")
        if HAT in r["path"]:
            assert cap == ""                             # never a hoodie/sweats line on the hat
    assert videos.similarity_report(rows) == []
    # running the batch again reuses everything: same jobs, nothing new
    assert videos.plan_batch(conn, db_settings, variants=1)["job_ids"] == plan["job_ids"]


@needs_ffmpeg
def test_similarity_flags_identical_versions(tmp_path):
    clip = studio.make_test_clip(tmp_path / "c.mp4", seconds=4.0)
    out = studio.render(clip, studio.RenderSpec(caption="x"), tmp_path / "o")["output"]
    copy = Path(out).with_name("copy.mp4")
    shutil.copy(out, copy)
    rows = [{"id": 1, "asset_id": 1, "qc_passed": True, "output_path": out, "spec": {"caption": "x"}},
            {"id": 2, "asset_id": 1, "qc_passed": True, "output_path": str(copy), "spec": {"caption": "x"}}]
    assert len(videos.similarity_report(rows)) == 1
