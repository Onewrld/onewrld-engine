"""Video Studio: turns a raw clip into a finished 9:16 post.

One render = one call to ffmpeg (the standard command-line video tool) that:
  1. reframes the clip to 1080x1920 (crop to fill, optional slow zoom)
  2. applies a look (natural or black-and-white)
  3. lays the logo watermark and the caption image on top
  4. evens out the volume (loudness normalization to -14 LUFS, the level the
     big platforms play at; LUFS = a standard unit of perceived loudness)
  5. adds the 1.5-second end card
Then quality_check() inspects the file before it may be used.

A "variant" is the same clip rendered with different settings (look, crop, zoom,
length, caption), so one source gives several distinct posts.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from onewrld import overlays, speech
from onewrld.errors import PermanentError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)

# Bump when the render pipeline changes in a way that changes the output (e.g. the audio
# chain), so old cached renders aren't reused. 2 = Phase 3.2 voice cleanup + measured gain.
RENDER_VERSION = 3  # 3 = photo framing variants, caption band, sentence line breaks
FPS = 30
STILL_BOX, STILL_TOP = 960, 260          # photo placement for fit="contain"
STILL_CAPTION_Y = 1320                    # caption sits under the photo
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
END_CARD_SECONDS = 1.5
TARGET_LUFS = -14.0
MIN_SECONDS, MAX_SECONDS = 3.0, 90.0
# Voice cleanup before leveling: cut rumble below 70 Hz, then compress (4:1 above
# about -26 dB) so sharp peaks don't stop the leveler reaching -14 LUFS. Same idea as the
# voice chain podcast and social editors use.
AUDIO_CLEAN = "highpass=f=70,acompressor=threshold=0.05:ratio=4:attack=2:release=120:makeup=3"


@dataclass(frozen=True)
class RenderSpec:
    """Everything that defines one output. Same spec + same source = same file."""
    caption: str = ""
    look: str = "natural"        # natural | bw
    crop_x: float = 0.5          # 0 = left edge of the frame, 0.5 = center, 1 = right
    zoom: float = 1.0            # 1.0 = none; 1.08 = slow push-in to 108%
    max_seconds: float = 30.0
    start: float = 0.0
    end_card: bool = True
    watermark: bool = True
    speech_captions: bool = False  # word-by-word captions from the speech (replaces `caption` on screen)
    cut_silence: bool = False      # cut pauses longer than speech.MAX_GAP
    fit: str = "fill"              # fill = crop to fill the frame (video); contain = whole
                                   # picture on black with room for the caption (photos)

    def key(self, source_sha: str) -> str:
        blob = json.dumps({"src": source_sha, "v": RENDER_VERSION, **asdict(self)}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def require_ffmpeg() -> None:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise PermanentError("ffmpeg is not installed. On Windows run: winget install Gyan.FFmpeg "
                             "then close and reopen PowerShell (RUNBOOK section 0).")


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: Path) -> dict:
    require_ffmpeg()
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)], capture_output=True, text=True)
    if out.returncode != 0:
        raise PermanentError(f"Not a readable video: {path.name} ({out.stderr.strip()[:200]})")
    data = json.loads(out.stdout)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise PermanentError(f"No video stream in {path.name}")
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    num, den = (v.get("avg_frame_rate") or "0/1").split("/")
    return {
        "duration": float(data["format"].get("duration", 0)),
        "width": int(v["width"]), "height": int(v["height"]),
        "fps": round(float(num) / float(den), 2) if float(den) else 0.0,
        "vcodec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
        "has_audio": a is not None, "acodec": a.get("codec_name") if a else None,
        "size_bytes": int(data["format"].get("size", 0)),
    }


def _video_chain(spec: RenderSpec, seconds: float) -> str:
    """ffmpeg filter text for the main clip's picture."""
    W, H = overlays.W, overlays.H
    if spec.fit == "contain":
        # whole picture, up to 960x960, placed in the upper safe area on black
        parts = [f"scale={STILL_BOX}:{STILL_BOX}:force_original_aspect_ratio=decrease",
                 f"pad={W}:{H}:(ow-iw)/2:{STILL_TOP}:black", f"fps={FPS}"]
        # Photos always drift slowly (a still frame looks frozen). `zoom` sets the framing:
        # 1.0 = whole product; higher = closer on the detail. The drift adds +4% over the clip.
        # crop_x moves the focus left/right (0.5 = center).
        frames = max(1, int(seconds * FPS))
        cy = STILL_TOP + STILL_BOX // 2
        parts.append(f"zoompan=z='{spec.zoom:.3f}+0.04*on/{frames}':"
                     f"x='(iw-iw/zoom)*{spec.crop_x:.3f}':y='{cy}-({cy}/zoom)':"
                     f"d=1:s={W}x{H}:fps={FPS}")
        parts += [f"scale={W}:{H}", "setsar=1"]
        if spec.look == "bw":
            parts.append("hue=s=0,eq=contrast=1.08:brightness=-0.02")
        return ",".join(parts)
    parts = [
        # fill the 9:16 frame, then cut out the 1080x1920 window at crop_x
        f"scale={W}:{H}:force_original_aspect_ratio=increase",
        f"crop={W}:{H}:(iw-{W})*{spec.crop_x:.3f}:(ih-{H})/2",
        f"fps={FPS}",
    ]
    if spec.zoom > 1.0:
        # slow push-in from 100% to spec.zoom over the clip (zoompan: 1 output per input frame)
        frames = max(1, int(seconds * FPS))  # reach full zoom at the clip's end
        parts.append(f"zoompan=z='min(1+({spec.zoom:.3f}-1)*on/{frames},{spec.zoom:.3f})':"
                     f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}")
    parts += [f"scale={W}:{H}", "setsar=1"]
    if spec.look == "bw":
        parts.append("hue=s=0,eq=contrast=1.08:brightness=-0.02")
    return ",".join(parts)


def plan_speech(words: list, spec: RenderSpec, dur: float):
    """Words shifted to the clip's own timeline (0 = spec.start), the stretches to keep,
    and the words re-timed after the cuts. Returns (segments or None, words_for_captions)."""
    local = [speech.Word(w.text, round(w.start - spec.start, 3), round(w.end - spec.start, 3))
             for w in words if w.start >= spec.start and w.end <= spec.start + dur]
    if spec.cut_silence:
        segs = speech.keep_segments(local, dur)
        return segs, speech.remap(local, segs)
    return None, local


PEAK_LIMIT = 0.84  # about -1.5 dBFS: headroom so platforms' own encoding doesn't distort


def _loudnorm(measured: dict | None) -> str:
    """Pass 2 of loudness leveling. With a measurement: apply the exact gain needed to reach
    TARGET_LUFS, then a limiter catches only the peaks that would go over -1.5 dB. (The
    loudnorm filter's own 'linear' mode refuses to add gain to peaky audio such as phone
    voice recordings, and undershoots by 3 to 4 dB; see M-009.)
    Without a measurement: loudnorm's single-pass mode as a fallback."""
    if not measured:
        return f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11"
    gain = max(-20.0, min(30.0, TARGET_LUFS - float(measured["input_i"])))
    return f"volume={gain:.2f}dB,alimiter=limit={PEAK_LIMIT}:attack=5:release=50:level=false"


def measure_loudness(src: Path, spec: RenderSpec, dur: float, apre: str) -> dict | None:
    """Pass 1 of two-pass loudness leveling: measure the exact audio that will be used
    (same trim and cuts), so pass 2 can apply one precise, even correction."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{spec.start:.3f}", "-t", f"{dur:.3f}",
           "-i", str(src), "-af", f"{apre}aresample=48000,{AUDIO_CLEAN},{_loudnorm(None)}:print_format=json",
           "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out.stderr, re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    try:
        if float(data["input_i"]) < -70:  # silence: nothing to level
            return None
    except ValueError:
        return None
    return data


def _caption_y(spec: RenderSpec) -> int:
    return STILL_CAPTION_Y if spec.fit == "contain" else 1180


def prepare_still(src: Path, workdir: Path) -> Path:
    """Flatten a photo onto black (removes transparency) and save it as a plain image."""
    from PIL import Image
    img = Image.open(src).convert("RGBA")
    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
    bg.alpha_composite(img)
    out = workdir / "still.png"
    bg.convert("RGB").save(out)
    return out


def build_command(src: Path, src_info: dict, spec: RenderSpec, out: Path, workdir: Path,
                  words: list | None = None, loudness: dict | None = None) -> list[str]:
    """Build (but don't run) the ffmpeg command. Kept separate so tests can inspect it.
    `words` (from speech.transcribe) are needed for speech_captions and cut_silence.
    Run the command with cwd=workdir: subtitle and font files are referenced by relative
    name, which avoids Windows drive-letter path problems in ffmpeg filters."""
    dur = max(0.1, min(spec.max_seconds, src_info["duration"] - spec.start))
    segments, cap_words = (None, None)
    if spec.speech_captions or spec.cut_silence:
        if words is None:
            raise PermanentError("speech features need a transcript (words)")
        segments, cap_words = plan_speech(words, spec, dur)
    out_dur = sum(e - s for s, e in segments) if segments else dur
    if src_info.get("still"):
        cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS),
               "-t", f"{dur:.3f}", "-i", str(src_info["still"])]
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{spec.start:.3f}", "-t", f"{dur:.3f}",
               "-i", str(src)]
    inputs = 1
    overlay_inputs = []
    if spec.watermark:
        wm = workdir / "watermark.png"
        overlays.watermark_png(wm)
        cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(wm)]
        overlay_inputs.append(inputs)
        inputs += 1
    if spec.caption and not spec.speech_captions:
        cap = workdir / "caption.png"
        overlays.caption_png(spec.caption, cap, center_y=_caption_y(spec),
                             band=spec.fit == "contain")
        cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(cap)]
        overlay_inputs.append(inputs)
        inputs += 1
    if not src_info["has_audio"]:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_in = f"[{inputs}:a]"
        inputs += 1
    else:
        audio_in = "[0:a]"
    if spec.end_card:
        card = workdir / "endcard.png"
        overlays.end_card_png(card)
        cmd += ["-loop", "1", "-t", f"{END_CARD_SECONDS}", "-framerate", str(FPS), "-i", str(card),
                "-f", "lavfi", "-t", f"{END_CARD_SECONDS}", "-i", "anullsrc=r=48000:cl=stereo"]
        card_v, card_a = inputs, inputs + 1
        inputs += 2

    vpre, apre = "", ""
    if segments:
        expr = speech.select_expr(segments)
        vpre = f"fps={FPS},select='{expr}',setpts=N/({FPS}*TB),"
        apre = f"aselect='{expr}',asetpts=N/SR/TB,"
    vpost = ""
    if spec.speech_captions and cap_words:
        speech.write_ass(cap_words, workdir / "captions.ass")
        fonts = workdir / "fonts"
        fonts.mkdir(exist_ok=True)
        shutil.copy(overlays.FONT_PATH, fonts / overlays.FONT_PATH.name)
        vpost = ",subtitles=captions.ass:fontsdir=fonts"
    fc = [f"[0:v]{vpre}{_video_chain(spec, out_dur)}{vpost}[base]"]
    last = "base"
    for i, idx in enumerate(overlay_inputs):
        fc.append(f"[{last}][{idx}:v]overlay=0:0:shortest=1[ov{i}]")
        last = f"ov{i}"
    fc.append(f"[{last}]format=yuv420p[mainv]")
    if not src_info["has_audio"]:
        apre = ""  # the silent stand-in track is already the right length for an uncut clip
    clean = f"{AUDIO_CLEAN}," if src_info["has_audio"] else ""
    fc.append(f"{audio_in}{apre}aresample=48000,{clean}{_loudnorm(loudness)},aresample=48000[maina]")
    if spec.end_card:
        fc.append(f"[{card_v}:v]scale={overlays.W}:{overlays.H},fps={FPS},setsar=1,format=yuv420p[cv]")
        fc.append(f"[{card_a}:a]aresample=48000[ca]")
        fc.append("[mainv][maina][cv][ca]concat=n=2:v=1:a=1[outv][outa]")
        vmap, amap = "[outv]", "[outa]"
    else:
        vmap, amap = "[mainv]", "[maina]"
    cmd += ["-filter_complex", ";".join(fc), "-map", vmap, "-map", amap,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(out)]
    return cmd


def measure_lufs(path: Path) -> float | None:
    """Integrated loudness of a file, using ffmpeg's ebur128 meter."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                          "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", out.stderr)
    return float(m[-1]) if m else None


def quality_check(path: Path, spec: RenderSpec, caption_box: overlays.Box | None,
                  silent_source: bool) -> dict:
    """Inspect a finished file. Every check must pass or the render is marked failed."""
    info = probe(path)
    expected_extra = END_CARD_SECONDS if spec.end_card else 0
    checks = {
        "resolution 1080x1920": (info["width"], info["height"]) == (overlays.W, overlays.H),
        "video codec h264, yuv420p": info["vcodec"] == "h264" and info["pix_fmt"] == "yuv420p",
        f"frame rate {FPS}": abs(info["fps"] - FPS) < 0.5,
        f"length {MIN_SECONDS:.0f}-{MAX_SECONDS + expected_extra:.0f}s":
            MIN_SECONDS <= info["duration"] <= MAX_SECONDS + expected_extra + 0.5,
        "has audio track (aac)": info["has_audio"] and info["acodec"] == "aac",
        "file under 250 MB": info["size_bytes"] < 250 * 1024 * 1024,
        "caption inside safe zone": caption_box is None or overlays.SAFE.contains(caption_box),
    }
    lufs = measure_lufs(path)
    if not silent_source:
        checks[f"loudness {TARGET_LUFS:.0f} LUFS (+/-3)"] = (
            lufs is not None and abs(lufs - TARGET_LUFS) <= 3.0)
    return {"passed": all(checks.values()), "checks": checks, "lufs": lufs, "info": info}


def render(src: Path, spec: RenderSpec, out_dir: Path, words_provider=None) -> dict:
    """Render one spec. Idempotent: if the same output already exists and passed, reuse it.
    words_provider(src, sha) -> list[speech.Word] is used for speech features; by default it
    transcribes with faster-whisper (cached under out_dir/.transcripts)."""
    require_ffmpeg()
    if src.suffix.lower() in IMAGE_EXTS:
        if spec.speech_captions or spec.cut_silence:
            raise PermanentError("speech features need a video with sound, not a photo")
        if spec.fit != "contain":
            spec = replace(spec, fit="contain")
        src_info = {"duration": spec.max_seconds, "has_audio": False, "still": None}
    else:
        src_info = probe(src)
    if src_info["duration"] - spec.start < MIN_SECONDS:
        raise PermanentError(f"{src.name} is too short to cut from ({src_info['duration']:.1f}s)")
    sha = file_sha(src)
    words = None
    if spec.speech_captions or spec.cut_silence:
        if not src_info["has_audio"]:
            raise PermanentError(f"{src.name} has no audio, so speech features can't be used")
        provider = words_provider or (lambda p, h: speech.transcribe(p, out_dir / ".transcripts", h))
        words = provider(src, sha)
        if not words:
            raise PermanentError(f"No speech found in {src.name}")
    key = spec.key(sha)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}_{key}.mp4"
    work = out_dir / f".work_{key}"
    work.mkdir(exist_ok=True)
    if "still" in src_info:
        src_info["still"] = prepare_still(src, work)
    caption_box = (overlays.caption_png(spec.caption, work / "caption_check.png",
                                        center_y=_caption_y(spec))
                   if spec.caption and not spec.speech_captions else None)
    if not out.exists():
        loud = None
        if src_info["has_audio"]:
            dur = max(0.1, min(spec.max_seconds, src_info["duration"] - spec.start))
            apre = ""
            if spec.cut_silence and words:
                segs, _ = plan_speech(words, spec, dur)
                apre = f"aselect='{speech.select_expr(segs)}',asetpts=N/SR/TB,"
            loud = measure_loudness(src, spec, dur, apre)
        cmd = build_command(src, src_info, spec, out, work, words, loud)
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=work)
        if proc.returncode != 0:
            out.unlink(missing_ok=True)
            raise PermanentError(f"ffmpeg failed: {proc.stderr.strip()[-400:]}")
    srt = None
    if spec.speech_captions and words is not None:
        _segs, cap_words = plan_speech(words, spec, max(0.1, min(spec.max_seconds,
                                                                src_info["duration"] - spec.start)))
        srt = str(speech.write_srt(cap_words, out.with_suffix(".srt")))
    qc = quality_check(out, spec, caption_box, silent_source=not src_info["has_audio"])
    shutil.rmtree(work, ignore_errors=True)
    log.info(f"Rendered {out.name}: QC {'passed' if qc['passed'] else 'FAILED'}")
    return {"key": key, "source_sha": sha, "output": str(out), "spec": asdict(spec), "qc": qc,
            "srt": srt}


def variant_specs(base: RenderSpec, captions: list[str], n: int, src_seconds: float) -> list[RenderSpec]:
    """The main version plus up to n distinct variants. Each changes several things at once
    (look, crop, zoom, length, caption) so they are not near-copies of each other.
    Photos use framing recipes instead: ONEWRLD's products are black and white, so a
    black-and-white version of a product photo looks identical (caught by the similarity
    check, see M-010)."""
    caps = captions or [base.caption]
    pick = lambda i: caps[i % len(caps)]
    short = max(MIN_SECONDS + 1, min(base.max_seconds, src_seconds) * 0.6)
    if base.fit == "contain":
        recipes = [
            dict(),                                         # whole product
            dict(zoom=1.35),                                # closer on the detail
            dict(zoom=1.8, crop_x=0.5, look="bw"),          # tight detail crop
            dict(zoom=1.2, crop_x=0.3, max_seconds=short),  # short, off-center
            dict(zoom=1.6, crop_x=0.7),
            dict(zoom=2.2, look="bw"),
        ]
        return [replace(base, caption=pick(i), **r) for i, r in enumerate(recipes[: n + 1])]
    recipes = [
        dict(),                                                  # main
        dict(look="bw"),
        dict(crop_x=0.3, zoom=1.08),
        dict(look="bw", max_seconds=short, zoom=1.05),
        dict(crop_x=0.7),
        dict(look="bw", crop_x=0.4, zoom=1.1),
    ]
    # Versions 7-10 (high-volume portal, D-067): start later in the clip as well, so even a
    # big team never gets two versions that open on the same frame.
    later = round(min(src_seconds * 0.2, max(0.0, src_seconds - short)), 2)
    recipes += [
        dict(start=later, max_seconds=short, crop_x=0.6),
        dict(start=later, look="bw", zoom=1.12, crop_x=0.45),
        dict(crop_x=0.2, zoom=1.15),
        dict(start=later, look="bw", crop_x=0.8, max_seconds=short),
    ]
    specs = []
    for i, r in enumerate(recipes[: n + 1]):
        specs.append(replace(base, caption=pick(i), **r))
    return specs


def make_test_clip(out: Path, seconds: float = 8.0) -> Path:
    """A synthetic landscape clip with a tone, for `render-test` (no footage needed)."""
    require_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={seconds}",
           "-filter:a", "volume=0.2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise PermanentError(f"Could not make test clip: {proc.stderr[-300:]}")
    return out
