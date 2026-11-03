"""Async fetches over :mod:`firms_client.sources` and :mod:`firms_client.hotspots`.

They take your ``httpx.AsyncClient``: timeouts, retries and pooling stay
yours, and transport errors propagate.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from firms_client.errors import FirmsError
from firms_client.hotspots import Hotspot, is_hotspot_csv, parse_csv
from firms_client.sources import ArchiveProduct, BBox, archive_url, area_url

if TYPE_CHECKING:
    import httpx


async def fetch_archive_csv(
    client: httpx.AsyncClient, product: ArchiveProduct, year: int, country: str
) -> str | None:
    """The raw yearly CSV, or ``None`` when that year is not published."""
    response = await client.get(archive_url(product, year, country))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    if not is_hotspot_csv(response.text):
        raise FirmsError(f"FIRMS archive did not return a CSV: {response.text[:200]!r}")
    return response.text


async def fetch_archive(
    client: httpx.AsyncClient, product: ArchiveProduct, year: int, country: str
) -> list[Hotspot] | None:
    """One year of a country's archive, parsed; ``None`` when not published."""
    text = await fetch_archive_csv(client, product, year, country)
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
