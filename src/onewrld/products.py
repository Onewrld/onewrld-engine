"""Products: the in-stock catalog (brand/products.toml) and its photos.

`pull-products` downloads each product's public store photos to media/products/<handle>/,
so the Volume Engine can turn them into videos. Downloads are skipped if already present.
"""

from __future__ import annotations

import tomllib
import urllib.request
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from onewrld.brand import BRAND_DIR
from onewrld.config import Settings
from onewrld.errors import RetryableError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@lru_cache(maxsize=1)
def _catalog(mtime: float) -> list[dict]:
    return tomllib.loads((BRAND_DIR / "products.toml").read_text(encoding="utf-8"))["products"]


def catalog() -> list[dict]:
    path = BRAND_DIR / "products.toml"
    return _catalog(path.stat().st_mtime)


def by_handle(handle: str) -> dict | None:
    return next((p for p in catalog() if p["handle"] == handle), None)


def caption_targets(handle: str | None) -> list[str] | None:
    """Which caption `product` tags may appear on this product: the product itself, its
    collection, and brand-wide lines. None = no filter (unknown footage)."""
    if not handle:
        return None
    p = by_handle(handle)
    targets = [handle, "brand"]
    if p and p.get("collection"):
        targets.append(f"collection:{p['collection']}")
    return targets


def products_dir(settings: Settings) -> Path:
    return settings.root / "media" / "products"


def pull_images(settings: Settings, opener=urllib.request.urlopen) -> list[Path]:
    """Download every catalog photo that isn't on disk yet. Returns all photo paths."""
    paths = []
    for p in catalog():
        folder = products_dir(settings) / p["handle"]
        folder.mkdir(parents=True, exist_ok=True)
        for i, url in enumerate(p.get("images", []), 1):
            ext = Path(urlparse(url).path).suffix.lower() or ".jpg"
            dest = folder / f"{i}{ext}"
            if not dest.exists():
                req = urllib.request.Request(url, headers={"User-Agent": "onewrld-engine"})
                try:
                    with opener(req, timeout=30) as r:
                        data = r.read()
                except OSError as e:
                    raise RetryableError(f"Could not download {url}: {e}") from None
                dest.write_bytes(data)
                log.info(f"Downloaded {p['handle']}/{dest.name}")
            paths.append(dest)
    return paths
