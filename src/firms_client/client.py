"""Async fetches over :mod:`firms_client.sources` and :mod:`firms_client.hotspots`.

They take your ``httpx.AsyncClient``: timeouts, retries and pooling stay
yours, and transport errors propagate.

Yearly archives are downloaded once into a data directory and read from
there afterwards: they are static, and a national VIIRS year is a few MB.
Downloads are streamed to a ``.part`` file and renamed when complete, so a
file that exists is whole. The area API is near-real-time and never cached.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from firms_client.errors import FirmsError
from firms_client.hotspots import Hotspot, is_hotspot_csv, parse_csv
from firms_client.sources import ArchiveProduct, BBox, archive_filename, archive_url, area_url

if TYPE_CHECKING:
    import httpx

#: The environment variable :func:`default_directory` reads.
ENV_DATA_DIR = "FIRMS_DATA_DIR"

_CHUNK = 1 << 16


def default_directory() -> Path:
    """Where archives go when no directory is given.

    ``FIRMS_DATA_DIR`` if set, else ``firms-client`` in the user cache
    (``$XDG_CACHE_HOME``, or ``~/.cache``).
    """
    if configured := os.environ.get(ENV_DATA_DIR, "").strip():
        return Path(configured).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME", "").strip() or "~/.cache"
    return Path(cache).expanduser() / "firms-client"


async def download_archive(
    client: httpx.AsyncClient,
    product: ArchiveProduct,
    year: int,
    country: str,
    directory: Path | None = None,
) -> Path | None:
    """The yearly CSV in ``directory``, downloaded if missing; ``None`` when not published.

    ``directory`` defaults to :func:`default_directory`. A file already there
    is returned without asking FIRMS; delete it to download it again. A year
    not published is not remembered, since it may be published later.
    """
    directory = directory or default_directory()
    path = directory / archive_filename(product, year, country)
    if path.exists():
        return path
    directory.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.part")
    try:
        async with client.stream("GET", archive_url(product, year, country)) as response:
            if response.status_code == 404:
                return None
            response.raise_for_status()
            with partial.open("wb") as out:
                async for chunk in response.aiter_bytes(_CHUNK):
                    out.write(chunk)
        with partial.open(encoding="utf-8", errors="replace") as part:
            head = part.read(400)
        if not is_hotspot_csv(head):
            raise FirmsError(f"FIRMS archive did not return a CSV: {head[:200]!r}")
        partial.rename(path)
    finally:
        partial.unlink(missing_ok=True)
    return path


async def fetch_archive_csv(
    client: httpx.AsyncClient,
    product: ArchiveProduct,
    year: int,
    country: str,
    directory: Path | None = None,
) -> str | None:
    """The raw yearly CSV, via :func:`download_archive`; ``None`` when not published."""
    path = await download_archive(client, product, year, country, directory)
    return path.read_text(encoding="utf-8") if path is not None else None


async def fetch_archive(
    client: httpx.AsyncClient,
    product: ArchiveProduct,
    year: int,
    country: str,
    directory: Path | None = None,
) -> list[Hotspot] | None:
    """One year of a country's archive, parsed; ``None`` when not published."""
    text = await fetch_archive_csv(client, product, year, country, directory)
    return parse_csv(text) if text is not None else None


async def fetch_area(
    client: httpx.AsyncClient,
    map_key: str,
    source: str,
    bbox: BBox,
    *,
    days: int = 1,
    on_date: date | None = None,
) -> list[Hotspot]:
    """Detections of ``source`` over ``bbox``. A bad key or source raises :class:`FirmsError`."""
    response = await client.get(area_url(map_key, source, bbox, days=days, on_date=on_date))
    if response.status_code != 200 or not is_hotspot_csv(response.text):
        if response.status_code == 200 and not response.text.strip():
            return []
        raise FirmsError(
            f"FIRMS area API (HTTP {response.status_code}): {response.text[:200].strip()}"
        )
    return parse_csv(response.text)
