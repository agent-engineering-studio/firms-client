"""Where FIRMS publishes hotspots, and what needs a key.

**Per-country archives, open.** The download portal asks for an Earthdata
login and delivers by e-mail, but FIRMS also serves static yearly CSVs per
country, with no account::

    https://firms.modaps.eosdis.nasa.gov/data/country/{product}/{year}/{product}_{year}_{country}.csv

Checked on 2026-11-03 for Italy: ``modis`` from 2000 and ``viirs-snpp`` from
2012, both up to 2025; ``viirs-noaa20`` and ``viirs-noaa21`` are not
published per country at all. A year not (yet) published answers 404 with a
JSON body. The archives are standard processing (SP) and carry ``type``.

**Area API, with a MAP_KEY.** Near-real-time detections over a bbox, free
key from https://firms.modaps.eosdis.nasa.gov/api/map_key/::

    https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{w,s,e,n}/{days}[/{YYYY-MM-DD}]

``days`` is 1 to 5. Without a date it is the last ``days`` days up to
today; with a date it runs **forward** from it: ``DATE .. DATE + days - 1``.
The ``*_SP`` sources are standard processing, months behind but complete.
A bad key or source is HTTP 400 with plain text (``Invalid MAP_KEY.``).
A key allows 5,000 transactions per 10 minutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

ARCHIVE_BASE = "https://firms.modaps.eosdis.nasa.gov/data/country"
AREA_API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

#: Near-real-time area API sources, about 3 hours behind the overpass.
NRT_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")

#: Standard-processing area API sources, months behind but complete.
SP_SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_SP", "MODIS_SP")

#: The most days the area API returns in one request.
MAX_AREA_DAYS = 5

#: (west, south, east, north), degrees.
BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class ArchiveProduct:
    """A product published as per-country yearly archives."""

    slug: str
    first_year: int


MODIS = ArchiveProduct(slug="modis", first_year=2000)
VIIRS_SNPP = ArchiveProduct(slug="viirs-snpp", first_year=2012)
ARCHIVE_PRODUCTS = (MODIS, VIIRS_SNPP)


def archive_filename(product: ArchiveProduct, year: int, country: str) -> str:
    """The name FIRMS gives the yearly CSV: ``viirs-snpp_2025_Italy.csv``."""
    return f"{product.slug}_{year}_{country}.csv"


def archive_url(product: ArchiveProduct, year: int, country: str) -> str:
    """The yearly CSV of ``country`` (English name, as FIRMS writes it: ``Italy``)."""
    return f"{ARCHIVE_BASE}/{product.slug}/{year}/{archive_filename(product, year, country)}"


def archive_years(product: ArchiveProduct, *, until: int) -> list[int]:
    """The years worth asking for, from the product's first."""
    return list(range(product.first_year, until + 1))


def area_url(
    map_key: str, source: str, bbox: BBox, *, days: int = 1, on_date: date | None = None
) -> str:
    """The area API URL.

    Without ``on_date``, the last ``days`` days up to today; with it, the
    ``days`` days starting on ``on_date``. ``days`` is 1 to 5.
    """
    if not 1 <= days <= MAX_AREA_DAYS:
        raise ValueError(f"days must be 1 to {MAX_AREA_DAYS}, got {days}")
    area = ",".join(f"{c:g}" for c in bbox)
    url = f"{AREA_API_BASE}/{map_key}/{source}/{area}/{days}"
    return f"{url}/{on_date.isoformat()}" if on_date is not None else url


def area_windows(start: date, end: date) -> list[tuple[date, int]]:
    """``(on_date, days)`` pairs covering ``start`` to ``end``, both included."""
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    windows = []
    day = start
    while day <= end:
        days = min(MAX_AREA_DAYS, (end - day).days + 1)
        windows.append((day, days))
        day += timedelta(days=days)
    return windows
