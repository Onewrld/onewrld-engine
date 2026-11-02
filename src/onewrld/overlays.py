"""Overlays: the graphics laid over a video (caption text, logo watermark, end card).

Drawn with Pillow as transparent PNG images, then ffmpeg places them on the video.
(Drawing text inside ffmpeg breaks easily on Windows file paths; images don't.)

Safe zone = the part of a 9:16 frame NOT covered by the app's own buttons and text.
TikTok/Reels/Shorts put their UI along the top, the bottom (caption + music bar) and
the right edge (like/comment buttons). Anything important must stay inside SAFE.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from onewrld.config import PROJECT_ROOT

W, H = 1080, 1920
FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "Assistant-Variable.ttf"
LOGO_PATH = PROJECT_ROOT / "assets" / "brand" / "logo_white_transparent.png"


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    def contains(self, other: "Box") -> bool:
        return (other.left >= self.left and other.top >= self.top
                and other.right <= self.right and other.bottom <= self.bottom)


# Keep text and logo inside this box (pixels, for 1080x1920).
SAFE = Box(left=60, top=250, right=W - 150, bottom=H - 500)


def _font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_PATH), size)
    try:
        f.set_variation_by_name(weight)
    except (OSError, ValueError):
        pass  # non-variable font: use as is
    return f


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _balanced_wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Same number of lines as a plain wrap, but with lines as even as possible,
    so a caption never ends with one lonely word."""
    lines = _wrap(draw, text, font, max_width)
    if len(lines) < 2:
        return lines
    lo, hi = 1, max_width
    best = lines
    while lo <= hi:  # find the narrowest width that still needs the same number of lines
        mid = (lo + hi) // 2
        trial = _wrap(draw, text, font, mid)
        if len(trial) <= len(lines) and all(draw.textlength(l, font=font) <= mid or " " not in l
                                            for l in trial):
            best, hi = trial, mid - 1
        else:
            lo = mid + 1
    return best


def caption_png(text: str, out: Path, size: int = 64, center_y: int = 1180) -> Box:
    """Full-frame transparent PNG with the caption centered in the safe zone.
    Shrinks the font until the text fits. Returns the text's bounding box."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    max_w = SAFE.right - SAFE.left - 40
    for s in range(size, 30, -4):
        font = _font(s)
        lines = _balanced_wrap(draw, text, font, max_w)
        line_h = int(s * 1.25)
        block_h = line_h * len(lines)
        if block_h <= (SAFE.bottom - SAFE.top) // 2:
            break
    top = max(SAFE.top, min(center_y - block_h // 2, SAFE.bottom - block_h))
    mid_x = (SAFE.left + SAFE.right) // 2
    left_edge, right_edge = W, 0
    for i, ln in enumerate(lines):
        w = draw.textlength(ln, font=font)
        x = int(mid_x - w / 2)
        y = top + i * line_h
        # dark outline keeps white text readable on bright footage
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255),
                  stroke_width=max(2, s // 20), stroke_fill=(0, 0, 0, 200))
        left_edge, right_edge = min(left_edge, x), max(right_edge, int(x + w))
    img.save(out)
    return Box(left_edge, top, right_edge, top + block_h)


def _logo(width: int) -> Image.Image:
    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo = logo.crop(logo.getchannel("A").getbbox())  # trim transparent margins
    ratio = width / logo.width
    return logo.resize((width, max(1, int(logo.height * ratio))), Image.LANCZOS)


def watermark_png(out: Path, width: int = 190, opacity: float = 0.85) -> Box:
    """Full-frame transparent PNG with a small logo in the top-left of the safe zone."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    logo = _logo(width)
    if opacity < 1:
        alpha = logo.getchannel("A").point(lambda a: int(a * opacity))
        logo.putalpha(alpha)
    x, y = SAFE.left + 10, SAFE.top + 10
    img.alpha_composite(logo, (x, y))
    img.save(out)
    return Box(x, y, x + logo.width, y + logo.height)


def end_card_png(out: Path, line: str = "onewrld.us") -> None:
    """Black frame: logo centered, store address underneath."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    logo = _logo(680)
    lx = (W - logo.width) // 2
    ly = H // 2 - logo.height
    img.alpha_composite(logo, (lx, ly))
    draw = ImageDraw.Draw(img)
    font = _font(48, "Regular")
    tw = draw.textlength(line, font=font)
    draw.text(((W - tw) / 2, ly + logo.height + 70), line, font=font, fill=(255, 255, 255, 230))
    img.convert("RGB").save(out)
