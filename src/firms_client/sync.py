"""Fill the data directory once, before it is needed: archives, mask, land cover.

The library reads lazily: an archive is downloaded the first time it is
asked for, the static mask is built the first time it is needed (from every
year of the archives, about 30 MB for Italy), and WorldCover is read from
its public bucket a block at a time. That suits a script or a notebook. A
server does better to do it all before its first request, and to work after
that without reaching NASA or ESA: :func:`sync` does exactly what the lazy
path would, in advance, and running it again costs nothing.

* the yearly archives of ``country``, for each product, from its first
  year (or ``first_year``) to last year;
* the static mask of the country, from those VIIRS S-NPP archives;
* with ``worldcover``, a local copy of ESA WorldCover over that box
  (:func:`~firms_client.landcover.save_worldcover`; the ``landcover`` extra).

It writes ``sync.json`` in the data directory: what is there, and when it
was synced. The current year is not in the archives; the near-real-time
area API covers it and is never cached.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from firms_client.client import default_directory, download_archive
from firms_client.mask import fetch_static_mask
from firms_client.retry import RetryPolicy
from firms_client.sources import VIIRS_SNPP, ArchiveProduct, BBox, archive_years

#: The manifest :func:`sync` writes in the data directory.
MANIFEST = "sync.json"


@dataclass(slots=True)
class SyncReport:
    """What :func:`sync` left in the data directory."""

    country: str
    directory: str
    archives: dict[str, list[int]] = field(default_factory=dict)
    missing: dict[str, list[int]] = field(default_factory=dict)
    mask: str | None = None
    mask_cells: int = 0
    worldcover: list[str] = field(default_factory=list)
    worldcover_bbox: BBox | None = None
    synced: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready."""
        return asdict(self)


async def sync(
    client: httpx.AsyncClient,
    country: str,
    *,
    products: tuple[ArchiveProduct, ...] = (VIIRS_SNPP,),
    first_year: int | None = None,
    last_year: int | None = None,
    worldcover: BBox | None = None,
    directory: Path | None = None,
    retry: RetryPolicy | None = None,
) -> SyncReport:
    """Download what the library would read lazily, now; see the module."""
    folder = directory or default_directory()
    last = last_year if last_year is not None else date.today().year - 1
    report = SyncReport(country=country, directory=str(folder))
    for product in products:
        for year in archive_years(product, until=last):
            if first_year is not None and year < first_year:
                continue
            path = await download_archive(client, product, year, country, folder, retry=retry)
            target = report.archives if path is not None else report.missing
            target.setdefault(product.slug, []).append(year)
    if VIIRS_SNPP in products and report.archives.get(VIIRS_SNPP.slug):
        mask = await fetch_static_mask(
            client,
            country,
            first_year=first_year,
            last_year=last,
            directory=folder,
            retry=retry,
        )
        first = first_year if first_year is not None else VIIRS_SNPP.first_year
        name = f"static-mask_{VIIRS_SNPP.slug}_{country}_{first}-{last}.json"
        report.mask = str(folder / name)
        report.mask_cells = len(mask.cells)
    if worldcover is not None:
        from firms_client.landcover import save_worldcover

        files = await asyncio.to_thread(save_worldcover, worldcover, folder)
        report.worldcover = [str(f) for f in files]
        report.worldcover_bbox = worldcover
    report.synced = datetime.now(UTC).isoformat(timespec="seconds")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MANIFEST).write_text(json.dumps(report.as_dict(), indent=2) + "\n")
    return report
