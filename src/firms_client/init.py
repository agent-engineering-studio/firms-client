"""Download what working offline needs, once: country archives and WorldCover tiles.

:func:`init` is the step a server or an installer runs before its first
request. It fetches, into the data directory:

* the yearly archives of ``country`` for ``years`` (VIIRS S-NPP by default),
  as :func:`~firms_client.download_archive` would on first use;
* the whole ESA WorldCover tiles (3 degrees a side, 2021, v200, CC BY 4.0)
  that touch ``bbox``, under the bucket's own path in ``worldcover/``, where
  :meth:`WorldCover.synced() <firms_client.WorldCover.synced>` reads them.
  A tile of open sea does not exist (HTTP 404) and is skipped. Over Italy:
  23 tiles, 1.3 GB. No ``rasterio`` is needed to download them.

A file already there is skipped, so running it again costs one request per
missing sea tile and nothing else; a download goes to a ``.part`` file and
is renamed when complete, so a file that exists is whole. A file that
fails is recorded and the rest goes on: run it again to resume.

It takes the caller's ``httpx.AsyncClient`` (or makes one) and retries
nothing unless given a :class:`~firms_client.RetryPolicy`: an application
with its own retry wraps the whole call, or calls
:func:`~firms_client.download_archive` and :func:`download_worldcover_tile`
one file at a time.

The static-source mask is not downloaded: it is built from the archives,
offline, the first time :func:`~firms_client.fetch_static_mask` is called.
:func:`~firms_client.sync` does all three, with a cropped WorldCover copy.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from firms_client.client import default_directory, download_archive
from firms_client.errors import FirmsError
from firms_client.landcover import WORLDCOVER_DIR, WORLDCOVER_URL, WorldCover
from firms_client.retry import RetryableStatusError, RetryPolicy, retryable, with_retries
from firms_client.sources import VIIRS_SNPP, ArchiveProduct, BBox, archive_filename

_CHUNK = 1 << 20
#: The side of a WorldCover tile, degrees.
TILE_DEG = 3


@dataclass(slots=True)
class InitReport:
    """What :func:`init` did, file by file (names, not paths)."""

    directory: str
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """No file failed: what exists is all there is."""
        return not self.failed

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready."""
        return {**asdict(self), "ok": self.ok}


def worldcover_tiles(bbox: BBox, *, year: int = 2021) -> list[str]:
    """The bucket URLs of the WorldCover tiles that touch ``bbox`` (west, south, east, north)."""
    west, south, east, north = bbox
    land = WorldCover(year=year)
    return [
        land.tile(lat + TILE_DEG / 2, lon + TILE_DEG / 2)
        for lat in range(
            math.floor(south / TILE_DEG) * TILE_DEG,
            math.ceil(north / TILE_DEG) * TILE_DEG,
            TILE_DEG,
        )
        for lon in range(
            math.floor(west / TILE_DEG) * TILE_DEG, math.ceil(east / TILE_DEG) * TILE_DEG, TILE_DEG
        )
    ]


def worldcover_path(url: str, directory: Path | None = None) -> Path:
    """Where a tile of the bucket lives in the data directory."""
    return (
        (directory or default_directory()) / WORLDCOVER_DIR / url.removeprefix(WORLDCOVER_URL + "/")
    )


async def download_worldcover_tile(
    client: httpx.AsyncClient,
    url: str,
    directory: Path | None = None,
    *,
    retry: RetryPolicy | None = None,
) -> Path | None:
    """One whole WorldCover tile into the data directory; ``None`` if it does not exist (sea).

    A tile already there is returned without asking the bucket.
    """
    path = worldcover_path(url, directory)
    if path.exists():
        return path
    partial = path.with_name(f"{path.name}.part")

    async def attempt(final: bool) -> bool:
        async with client.stream("GET", url) as response:
            if response.status_code == 404:
                return False
            if retryable(retry, response, final):
                raise RetryableStatusError(response)
            response.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            with partial.open("wb") as out:
                async for chunk in response.aiter_bytes(_CHUNK):
                    out.write(chunk)
        return True

    try:
        if not await with_retries(retry, attempt):
            return None
        partial.rename(path)
    finally:
        partial.unlink(missing_ok=True)
    return path


async def init(
    directory: Path | None = None,
    *,
    country: str,
    years: Iterable[int],
    bbox: BBox | None = None,
    products: tuple[ArchiveProduct, ...] = (VIIRS_SNPP,),
    client: httpx.AsyncClient | None = None,
    retry: RetryPolicy | None = None,
) -> InitReport:
    """Archives of ``country`` for ``years`` and the WorldCover tiles over ``bbox``; see the module.

    ``directory`` defaults to :func:`~firms_client.default_directory`.
    ``missing`` lists the years not published (and the sea tiles), which
    are not errors; ``failed`` maps a file to its error.
    """
    folder = directory or default_directory()
    report = InitReport(directory=str(folder))
    own = client is None
    http = client or httpx.AsyncClient(timeout=600, follow_redirects=True)
    try:
        for product in products:
            for year in years:
                if year < product.first_year:
                    continue
                name = archive_filename(product, year, country)
                if (folder / name).exists():
                    report.skipped.append(name)
                    continue
                try:
                    found = await download_archive(
                        http, product, year, country, folder, retry=retry
                    )
                except (httpx.HTTPError, FirmsError, OSError) as error:
                    report.failed[name] = str(error) or type(error).__name__
                    continue
                (report.downloaded if found is not None else report.missing).append(name)
        for url in worldcover_tiles(bbox) if bbox is not None else []:
            name = url.rsplit("/", 1)[-1]
            if worldcover_path(url, folder).exists():
                report.skipped.append(name)
                continue
            try:
                found = await download_worldcover_tile(http, url, folder, retry=retry)
            except (httpx.HTTPError, OSError) as error:
                report.failed[name] = str(error) or type(error).__name__
                continue
            (report.downloaded if found is not None else report.missing).append(name)
    finally:
        if own:
            await http.aclose()
    return report
