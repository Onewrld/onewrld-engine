"""Test helper: build a talking clip whose word timings are known exactly.
Each word is synthesized separately (ffmpeg's flite text-to-speech) and placed with
chosen pauses, so tests can check cuts and captions without a speech model."""

import subprocess
from pathlib import Path

from onewrld import speech, studio


def _audio_seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


def flite_available() -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return " flite " in out.stdout


def make_spoken_clip(folder: Path, script: list[tuple[str, float]]) -> tuple[Path, list[speech.Word]]:
    """script = [(word, pause_after_seconds), ...]. Returns (clip, exact word timings)."""
    folder.mkdir(parents=True, exist_ok=True)
    pieces, words, t = [], [], 0.6  # start with 0.6s of dead air
    silence = folder / "sil.wav"
    for i, (word, pause) in enumerate(script):
        wav = folder / f"w{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"flite=text='{word}':voice=kal", "-ar", "48000", "-ac", "1", str(wav)],
                       check=True)
        d = _audio_seconds(wav)
        words.append(speech.Word(word, round(t, 3), round(t + d, 3)))
        pieces.append((wav, pause))
        t += d + pause
    # stitch: lead-in silence, then each word followed by its pause
    inputs, filters = [], []
    for i, (wav, pause) in enumerate(pieces):
        inputs += ["-i", str(wav)]
        filters.append(f"[{i}:a]apad=pad_dur={pause}[a{i}]")
    n = len(pieces)
    concat = "".join(f"[a{i}]" for i in range(n))
    audio = folder / "speech.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
                    ";".join(filters) + f";{concat}concat=n={n}:v=0:a=1,adelay=600[out]",
                    "-map", "[out]", "-ar", "48000", str(audio)], check=True)
    dur = _audio_seconds(audio)
    clip = folder / "talk.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size=1080x1920:rate=30:duration={dur:.3f}", "-i", str(audio),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
                   check=True)
    return clip, words
