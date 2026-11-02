"""Video Studio: overlays, render planning, a real render, and the quality gate."""

import shutil
import subprocess
from dataclasses import asdict

import pytest

from onewrld import overlays, studio

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


# --- overlays (no ffmpeg needed) ---------------------------------------------

@pytest.mark.parametrize("text", [
    "Fly.",
    "480 GSM cotton. You feel the weight the second you pick it up.",
    "Whatever got you here, keep doing it. The day you stop is the day it starts slipping. " * 3,
])
def test_caption_always_inside_safe_zone(tmp_path, text):
    box = overlays.caption_png(text, tmp_path / "c.png")
    assert overlays.SAFE.contains(box), box


def test_watermark_inside_safe_zone(tmp_path):
    assert overlays.SAFE.contains(overlays.watermark_png(tmp_path / "w.png"))


def test_balanced_wrap_has_no_orphan_word(tmp_path):
    from PIL import Image, ImageDraw
    draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    font = overlays._font(64)
    text = "480 GSM cotton. You feel the weight the second you pick it up."
    lines = overlays._balanced_wrap(draw, text, font, overlays.SAFE.right - overlays.SAFE.left - 40)
    assert len(lines) >= 2 and all(len(l.split()) >= 2 for l in lines), lines


# --- planning -----------------------------------------------------------------

def test_variants_are_distinct_and_keys_unique():
    specs = studio.variant_specs(studio.RenderSpec(), ["a", "b"], 3, 20.0)
    assert len(specs) == 4
    fingerprints = {(s.look, s.crop_x, s.zoom, s.max_seconds, s.caption) for s in specs}
    assert len(fingerprints) == 4
    assert len({s.key("sha") for s in specs}) == 4


def test_same_spec_same_key_different_source_different_key():
    s = studio.RenderSpec(caption="x")
    assert s.key("a") == s.key("a") != s.key("b")


def test_command_normalizes_loudness_and_adds_end_card(tmp_path):
    info = {"duration": 10.0, "has_audio": True}
    cmd = studio.build_command(tmp_path / "in.mp4", info, studio.RenderSpec(caption="x"),
                               tmp_path / "out.mp4", tmp_path)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "loudnorm=I=-14" in fc and "concat=n=2" in fc
    assert "-movflags" in cmd and "+faststart" in cmd


def test_silent_source_gets_a_silent_track(tmp_path):
    info = {"duration": 10.0, "has_audio": False}
    cmd = studio.build_command(tmp_path / "in.mp4", info, studio.RenderSpec(),
                               tmp_path / "out.mp4", tmp_path)
    assert any("anullsrc" in c for c in cmd)


# --- real renders (need ffmpeg) -------------------------------------------------

@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    return studio.make_test_clip(tmp_path_factory.mktemp("src") / "clip.mp4", seconds=4.0)


@needs_ffmpeg
def test_render_passes_quality_gate_and_is_idempotent(clip, tmp_path):
    spec = studio.RenderSpec(caption="480 GSM cotton.", look="bw", zoom=1.05)
    r = studio.render(clip, spec, tmp_path)
    assert r["qc"]["passed"], r["qc"]["checks"]
    info = r["qc"]["info"]
    assert (info["width"], info["height"]) == (1080, 1920)
    assert abs(info["duration"] - (4.0 + studio.END_CARD_SECONDS)) < 0.3
    mtime = (tmp_path / r["output"].split("/")[-1].split("\\")[-1]).stat().st_mtime
    r2 = studio.render(clip, spec, tmp_path)  # same spec: reuses the file
    assert r2["output"] == r["output"]
    assert (tmp_path / r["output"].split("/")[-1].split("\\")[-1]).stat().st_mtime == mtime


@needs_ffmpeg
def test_quality_gate_rejects_wrong_format(clip):
    # the raw landscape clip is not a finished vertical post
    qc = studio.quality_check(clip, studio.RenderSpec(end_card=False), None, silent_source=False)
    assert not qc["passed"]
    assert qc["checks"]["resolution 1080x1920"] is False


@needs_ffmpeg
def test_too_short_source_is_refused(tmp_path):
    from onewrld.errors import PermanentError
    short = studio.make_test_clip(tmp_path / "short.mp4", seconds=1.5)
    with pytest.raises(PermanentError, match="too short"):
        studio.render(short, studio.RenderSpec(), tmp_path / "out")


@needs_ffmpeg
def test_render_job_through_queue_records_result(db_settings, conn, clip, monkeypatch):
    from onewrld import captions, videos
    from onewrld.worker import run_worker

    # renders go to the throwaway project folder, never your real renders/ folder
    cid, _ = captions.add_caption(conn, "480 GSM cotton. You feel the weight.", pillar="product")
    captions.decide(conn, cid, "approved")
    asset = videos.register_asset(conn, clip)
    again = videos.register_asset(conn, clip)
    assert again["id"] == asset["id"]  # same file = same asset
    job_ids = videos.plan(conn, asset, variants=1, max_seconds=4.0)
    assert len(job_ids) == 2
    assert videos.plan(conn, asset, variants=1, max_seconds=4.0) == job_ids  # no duplicates
    stats = run_worker(db_settings, max_jobs=5, max_seconds=600)
    assert stats["done"] == 2, stats
    rows = conn.execute("SELECT qc_passed, caption_id, output_path FROM render").fetchall()
    assert len(rows) == 2 and all(r["qc_passed"] for r in rows)
    assert all(r["caption_id"] == cid for r in rows)
    assert all(str(db_settings.root) in r["output_path"] for r in rows)
