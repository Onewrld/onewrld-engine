"""Speech: find every spoken word and its exact time, then use that to
  (1) cut dead air: drop pauses longer than MAX_GAP seconds, and
  (2) build word-by-word captions that highlight each word as it is spoken.

Transcription uses faster-whisper: a free speech-recognition model that runs on your PC
(nothing is uploaded). It is an OPTIONAL install: `pip install -e ".[speech]"`.
Everything else in the system works without it.

Transcripts are cached per file fingerprint, so a clip is only transcribed once.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from onewrld.errors import PermanentError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_MODEL = "small.en"   # good accuracy on CPU; "base.en" is faster, "medium.en" more accurate
MAX_GAP = 0.6                # pauses longer than this (seconds) get cut
PAD = 0.12                   # keep this much air around each kept stretch, so cuts don't clip words
WORDS_PER_CHUNK = 4          # how many words show on screen at once


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


def speech_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def install_hint() -> str:
    return ('Speech features need an extra install:  pip install -e ".[speech]"  '
            "(needs Python 3.11 to 3.14; see RUNBOOK section 14).")


def transcribe(path: Path, cache_dir: Path, sha: str, model_size: str = DEFAULT_MODEL) -> list[Word]:
    """Words with start/end times. Cached in cache_dir/<sha>.<model>.json."""
    cache = cache_dir / f"{sha}.{model_size}.json"
    if cache.exists():
        return [Word(**w) for w in json.loads(cache.read_text(encoding="utf-8"))]
    if not speech_available():
        raise PermanentError(install_hint())
    from faster_whisper import WhisperModel

    log.info(f"Transcribing {path.name} with {model_size} (first run downloads the model)...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path), word_timestamps=True, vad_filter=True,
                                       beam_size=5, language="en")
    words = [Word(w.word.strip(), round(w.start, 3), round(w.end, 3))
             for seg in segments for w in (seg.words or []) if w.word.strip()]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([w.__dict__ for w in words]), encoding="utf-8")
    log.info(f"Transcribed {len(words)} words")
    return words


# --- dead-air cuts ---------------------------------------------------------------

def keep_segments(words: list[Word], duration: float, max_gap: float = MAX_GAP,
                  pad: float = PAD) -> list[tuple[float, float]]:
    """Stretches of the clip to KEEP: speech plus a little padding. Any pause longer than
    max_gap (including dead air at the start and end) is dropped."""
    if not words:
        return [(0.0, duration)]
    segs: list[list[float]] = []
    for w in words:
        s, e = max(0.0, w.start - pad), min(duration, w.end + pad)
        if segs and s - segs[-1][1] <= max_gap:
            segs[-1][1] = max(segs[-1][1], e)
        else:
            segs.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in segs if e - s > 0.05]


def remap(words: list[Word], segments: list[tuple[float, float]]) -> list[Word]:
    """Word times on the NEW timeline after the cuts (removed pauses shift later words earlier)."""
    out, offset = [], 0.0
    for s, e in segments:
        for w in words:
            if w.start >= s - 1e-6 and w.end <= e + 1e-6:
                out.append(Word(w.text, round(w.start - s + offset, 3), round(w.end - s + offset, 3)))
        offset += e - s
    return out


def select_expr(segments: list[tuple[float, float]]) -> str:
    """ffmpeg expression that is true inside the kept stretches."""
    return "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in segments)


# --- word-by-word captions (ASS subtitle format) ---------------------------------
# ASS is the standard styled-subtitle format; ffmpeg's `subtitles` filter burns it in.
# Colors in ASS are &HAABBGGRR. White = &H00FFFFFF, gray = &H00A0A0A0.

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,Assistant,78,&H00A0A0A0,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,0,5,80,170,0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def chunks(words: list[Word], size: int = WORDS_PER_CHUNK) -> list[list[Word]]:
    """Group words into short on-screen lines; a sentence end starts a new line."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= size or w.text.endswith((".", "?", "!")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def ass_events(words: list[Word], center_y: int = 1180) -> list[str]:
    """One event per spoken word: the whole chunk is shown, the current word in white,
    the rest in gray. That's the "active word highlight" look."""
    lines = []
    for chunk in chunks(words):
        for i, w in enumerate(chunk):
            end = chunk[i + 1].start if i + 1 < len(chunk) else w.end + 0.25
            parts = []
            for j, other in enumerate(chunk):
                t = _esc(other.text)
                parts.append("{\\c&H00FFFFFF&}" + t + "{\\c&H00A0A0A0&}" if j == i else t)
            text = "{\\an5\\pos(500," + str(center_y) + ")}" + " ".join(parts)
            lines.append(f"Dialogue: 0,{_ts(w.start)},{_ts(max(end, w.start + 0.05))},Word,,0,0,0,,{text}")
    return lines


def write_ass(words: list[Word], out: Path) -> Path:
    out.write_text(ASS_HEADER + "\n".join(ass_events(words)) + "\n", encoding="utf-8")
    return out


def write_srt(words: list[Word], out: Path) -> Path:
    """Plain subtitle sidecar file (.srt) for platforms that accept uploaded captions."""
    def ts(t: float) -> str:
        ms = int(round(max(0.0, t) * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    blocks = []
    for n, c in enumerate(chunks(words), 1):
        blocks.append(f"{n}\n{ts(c[0].start)} --> {ts(c[-1].end)}\n{' '.join(w.text for w in c)}\n")
    out.write_text("\n".join(blocks), encoding="utf-8")
    return out
