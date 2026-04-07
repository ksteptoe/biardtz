"""Fetch and cache bird images from Wikipedia/Wikidata Commons."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image

_logger = logging.getLogger(__name__)
_fetching: set[str] = set()
_semaphore = asyncio.Semaphore(3)

_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_COMMONS_THUMB = "https://upload.wikimedia.org/wikipedia/commons/thumb"


def _slug(sci_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", sci_name.lower()).strip("_")


def _commons_thumb_url(filename: str, width: int = 400) -> str:
    """Build a Wikimedia Commons thumbnail URL from a filename."""
    filename = filename.replace(" ", "_")
    md5 = hashlib.md5(filename.encode()).hexdigest()  # noqa: S324
    return f"{_COMMONS_THUMB}/{md5[0]}/{md5[:2]}/{quote(filename)}/{width}px-{quote(filename)}"


async def _fetch_image_url(sci_name: str) -> str | None:
    """Look up a bird's image URL via Wikidata."""
    async with httpx.AsyncClient(timeout=15) as client:
        # Search for the entity
        resp = await client.get(_WIKIDATA_API, params={
            "action": "wbsearchentities",
            "search": sci_name,
            "language": "en",
            "type": "item",
            "format": "json",
        })
        data = resp.json()
        results = data.get("search", [])
        if not results:
            return None

        entity_id = results[0]["id"]

        # Get the P18 (image) claim
        resp = await client.get(_WIKIDATA_API, params={
            "action": "wbgetclaims",
            "entity": entity_id,
            "property": "P18",
            "format": "json",
        })
        claims = resp.json().get("claims", {})
        p18 = claims.get("P18", [])
        if not p18:
            return None

        filename = p18[0]["mainsnak"]["datavalue"]["value"]
        return _commons_thumb_url(filename)


async def get_image_path(sci_name: str, cache_dir: Path) -> Path | None:
    """Get a cached bird image, fetching from Wikidata if needed."""
    slug = _slug(sci_name)
    cached = cache_dir / f"{slug}.jpg"
    marker = cache_dir / f"{slug}.none"

    if cached.exists():
        return cached
    if marker.exists():
        return None
    if slug in _fetching:
        return None

    _fetching.add(slug)
    try:
        async with _semaphore:
            url = await _fetch_image_url(sci_name)
            if not url:
                marker.touch()
                return None

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    marker.touch()
                    return None

                img = Image.open(io.BytesIO(resp.content))
                img.thumbnail((400, 400))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                cache_dir.mkdir(parents=True, exist_ok=True)
                img.save(cached, "JPEG", quality=85)
                _logger.info("Cached image for %s", sci_name)
                return cached
    except Exception:
        _logger.debug("Failed to fetch image for %s", sci_name, exc_info=True)
        marker.touch()
        return None
    finally:
        _fetching.discard(slug)
